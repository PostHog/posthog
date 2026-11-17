import * as core from '@actions/core'
import * as github from '@actions/github'
import {PullRequest} from '@octokit/webhooks-types'

import {ChangeStatus, File, filesFromApiRow} from './file'
import {Filter, FilterResults} from './filter'

const BUDGET_MS = 20000
const CAPTURE_TIMEOUT_MS = 2000
const COMPARE_FILE_CAP = 300
const MAX_HEADS_WALKED = 20
const MAX_SOURCE_AGE_MS = 24 * 60 * 60 * 1000
const DETAIL_SAMPLE = 5
const NULL_SHA = '0000000000000000000000000000000000000000'
const POSTHOG_HOST = 'https://us.i.posthog.com'
const EVENT_NAME = 'posthog-ci-reuse-decision'
const MERGE_QUEUE_BRANCH_PREFIX = 'trunk-merge/'
const PASSING_CONCLUSIONS = ['success', 'skipped']

export type Reason =
  | 'reused'
  | 'disabled'
  | 're-run'
  | 'not-a-push'
  | 'fork'
  | 'merge-queue'
  | 'blocking-label'
  | 'no-previous-head'
  | 'no-inputs'
  | 'file-list-truncated'
  | 'inputs-changed'
  | 'previous-not-green'
  | 'no-proven-run'
  | 'previous-ran-as-draft'
  | 'previous-too-old'
  | 'base-changed'
  | 'filter-changed'
  | 'budget-exceeded'
  | 'error'

export interface ReuseConfig {
  checks: string[]
  proofChecks: string[]
  filterSource: string | null
  keys: string[]
  blockingLabels: string[]
  disabled: boolean
}

export interface ReuseInput {
  config: ReuseConfig
  filter: Filter
  files: File[]
  truncated: boolean
  action: string | undefined
  before: string | undefined
  runAttempt: number
  now: number
  pr: PullRequest
}

export interface CheckRun {
  status: string
  conclusion: string | null
  startedAt: string | null
}

export interface PullTimeline {
  readyForReviewAt: string | null
  baseChangedAt: string | null
}

export interface ReuseApi {
  filesAt(baseSha: string, headSha: string): Promise<File[] | null>
  checkRuns(sha: string, name: string): Promise<CheckRun[]>
  pullCommits(pullNumber: number): Promise<string[]>
  timeline(pullNumber: number): Promise<PullTimeline>
  changedOnBranchSince(branch: string, path: string, since: string): Promise<boolean>
}

export interface Decision {
  reuse: boolean
  reason: Reason
  detail: string | null
  previousSha: string | null
  keys: string[]
  durationMs: number
  pr: PullRequest
}

class BudgetExceeded extends Error {}

function listInput(name: string): string[] {
  return core
    .getInput(name, {required: false})
    .split('\n')
    .map(item => item.trim())
    .filter(item => item.length > 0)
}

function workflowPath(): string | null {
  const workflowRef = process.env.GITHUB_WORKFLOW_REF
  const repository = process.env.GITHUB_REPOSITORY
  if (!workflowRef || !repository || !workflowRef.startsWith(`${repository}/`)) {
    return null
  }
  return workflowRef.slice(repository.length + 1).split('@')[0] || null
}

export function loadConfig(filter: Filter, filtersPath: string | null): ReuseConfig | null {
  const checks = listInput('reuse-checks')
  if (checks.length === 0) {
    return null
  }
  const proofChecks = listInput('reuse-proof-checks')
  if (proofChecks.length === 0) {
    throw new Error(`Input 'reuse-proof-checks' is required when 'reuse-checks' is set`)
  }
  const known = Object.keys(filter.rules)
  const requested = listInput('reuse-filters')
  const unknown = requested.filter(key => !known.includes(key))
  if (unknown.length > 0) {
    throw new Error(`Input 'reuse-filters' names filters that do not exist: ${unknown.join(', ')}`)
  }
  return {
    checks,
    proofChecks,
    filterSource: core.getInput('reuse-filter-source', {required: false}) || filtersPath || workflowPath(),
    keys: requested.length > 0 ? requested : known,
    blockingLabels: listInput('reuse-blocking-labels'),
    disabled: core.getInput('reuse-disabled', {required: false}).toLowerCase() === 'true'
  }
}

function inputsOf(filter: Filter, config: ReuseConfig, files: File[]): Map<string, string> | null {
  const matched = filter.match(files)
  const inputs = new Map<string, string>()
  const scoped = config.keys.flatMap(key => matched[key])
  const filterSource = files.filter(file => file.filename === config.filterSource)
  for (const file of [...scoped, ...filterSource]) {
    if (file.status === ChangeStatus.Deleted) {
      inputs.set(file.filename, file.status)
    } else if (file.sha) {
      inputs.set(file.filename, `${file.status}:${file.sha}`)
    } else {
      return null
    }
  }
  return inputs
}

function differingFiles(current: Map<string, string>, previous: Map<string, string>): string[] {
  const names = new Set([...current.keys(), ...previous.keys()])
  return [...names].filter(name => current.get(name) !== previous.get(name)).sort()
}

function isSha(value: string | undefined): value is string {
  return value !== undefined && /^[0-9a-f]{40}$/.test(value) && value !== NULL_SHA
}

type Verdict = Pick<Decision, 'reuse' | 'reason' | 'detail' | 'previousSha'>

function miss(reason: Reason, detail: string | null = null): Verdict {
  return {reuse: false, reason, detail, previousSha: null}
}

interface ProvenRun {
  sha: string
  startedAt: string
}

async function compareInputs(
  input: ReuseInput,
  api: ReuseApi,
  current: Map<string, string>,
  sha: string
): Promise<Verdict | null> {
  const previousFiles = await api.filesAt(input.pr.base.sha, sha)
  if (previousFiles === null) {
    return miss('file-list-truncated', sha)
  }
  const previous = inputsOf(input.filter, input.config, previousFiles)
  if (previous === null) {
    return miss('error', `a file at ${sha} has no blob sha`)
  }
  const differing = differingFiles(current, previous)
  if (differing.length > 0) {
    return miss('inputs-changed', differing.slice(0, DETAIL_SAMPLE).join(', '))
  }
  return null
}

async function headsToWalk(input: ReuseInput & {before: string}, api: ReuseApi): Promise<string[]> {
  const commits = await api.pullCommits(input.pr.number)
  const index = commits.lastIndexOf(input.before)
  if (index < 0) {
    return [input.before]
  }
  return commits.slice(Math.max(0, index - MAX_HEADS_WALKED + 1), index + 1).reverse()
}

async function proveRun(input: ReuseInput & {before: string}, api: ReuseApi): Promise<ProvenRun | Verdict> {
  const {config} = input
  for (const sha of await headsToWalk(input, api)) {
    const starts: string[] = []
    let missing = 0
    for (const name of config.checks) {
      const runs = await api.checkRuns(sha, name)
      if (runs.length === 0) {
        missing++
        continue
      }
      const notGreen = runs.find(run => !PASSING_CONCLUSIONS.includes(run.conclusion ?? ''))
      if (notGreen) {
        return miss('previous-not-green', `${sha} ${name}: ${notGreen.conclusion ?? notGreen.status}`)
      }
      starts.push(...runs.map(run => run.startedAt ?? ''))
    }
    if (missing === config.checks.length && sha !== input.before) {
      continue
    }
    if (missing > 0) {
      return miss('previous-not-green', `${sha}: no check run for ${missing} of ${config.checks.length} checks`)
    }
    for (const name of config.proofChecks) {
      const runs = await api.checkRuns(sha, name)
      if (runs.some(run => run.conclusion === 'success')) {
        return {sha, startedAt: starts.sort()[0]}
      }
    }
  }
  return miss('no-proven-run')
}

async function decide(input: ReuseInput, api: ReuseApi): Promise<Verdict> {
  const {config, filter, pr} = input
  if (config.disabled) {
    return miss('disabled')
  }
  if (input.runAttempt > 1) {
    return miss('re-run', String(input.runAttempt))
  }
  if (input.action !== 'synchronize') {
    return miss('not-a-push', input.action ?? null)
  }
  if (pr.head.repo?.full_name !== pr.base.repo.full_name) {
    return miss('fork')
  }
  if (pr.head.ref.startsWith(MERGE_QUEUE_BRANCH_PREFIX)) {
    return miss('merge-queue')
  }
  const blockingLabel = pr.labels.find(label => config.blockingLabels.includes(label.name))
  if (blockingLabel) {
    return miss('blocking-label', blockingLabel.name)
  }
  if (!config.filterSource) {
    return miss('error', 'the file that defines the filters is unknown')
  }
  const before = input.before
  if (!isSha(before)) {
    return miss('no-previous-head')
  }
  if (input.truncated) {
    return miss('file-list-truncated', 'current head')
  }
  const current = inputsOf(filter, config, input.files)
  if (current === null) {
    return miss('error', 'a current file has no blob sha')
  }
  if (current.size === 0) {
    return miss('no-inputs')
  }
  const againstPrevious = await compareInputs(input, api, current, before)
  if (againstPrevious) {
    return againstPrevious
  }
  const proven = await proveRun({...input, before}, api)
  if ('reason' in proven) {
    return proven
  }
  if (proven.sha !== before) {
    const againstProven = await compareInputs(input, api, current, proven.sha)
    if (againstProven) {
      return againstProven
    }
  }
  if (input.now - Date.parse(proven.startedAt) > MAX_SOURCE_AGE_MS) {
    return miss('previous-too-old', `${proven.sha} started ${proven.startedAt}`)
  }
  const timeline = await api.timeline(pr.number)
  if (!pr.draft && timeline.readyForReviewAt !== null && proven.startedAt < timeline.readyForReviewAt) {
    return miss('previous-ran-as-draft', proven.sha)
  }
  if (timeline.baseChangedAt !== null && timeline.baseChangedAt > proven.startedAt) {
    return miss('base-changed', timeline.baseChangedAt)
  }
  if (await api.changedOnBranchSince(pr.base.ref, config.filterSource, proven.startedAt)) {
    return miss('filter-changed', config.filterSource)
  }
  return {reuse: true, reason: 'reused', detail: null, previousSha: proven.sha}
}

export async function evaluate(input: ReuseInput, apiFor: (signal: AbortSignal) => ReuseApi): Promise<Decision> {
  const startedAt = Date.now()
  const controller = new AbortController()
  let timer: NodeJS.Timeout | undefined
  const expiry = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      controller.abort()
      reject(new BudgetExceeded())
    }, BUDGET_MS)
  })
  let verdict: Verdict
  try {
    verdict = await Promise.race([decide(input, apiFor(controller.signal)), expiry])
  } catch (error) {
    verdict =
      error instanceof BudgetExceeded
        ? miss('budget-exceeded', `${BUDGET_MS}ms`)
        : miss('error', error instanceof Error ? error.message : String(error))
  } finally {
    clearTimeout(timer)
  }
  return {...verdict, keys: input.config.keys, durationMs: Date.now() - startedAt, pr: input.pr}
}

export function withoutReusedKeys(results: FilterResults, keys: string[]): FilterResults {
  return Object.fromEntries(Object.entries(results).map(([key, files]) => [key, keys.includes(key) ? [] : files]))
}

const TIMELINE_QUERY = `
  query ($owner: String!, $name: String!, $number: Int!) {
    repository(owner: $owner, name: $name) {
      pullRequest(number: $number) {
        timelineItems(last: 100, itemTypes: [READY_FOR_REVIEW_EVENT, BASE_REF_CHANGED_EVENT, BASE_REF_FORCE_PUSHED_EVENT]) {
          nodes {
            __typename
            ... on ReadyForReviewEvent {
              createdAt
            }
            ... on BaseRefChangedEvent {
              createdAt
            }
            ... on BaseRefForcePushedEvent {
              createdAt
            }
          }
        }
      }
    }
  }
`

interface TimelineResponse {
  repository: {pullRequest: {timelineItems: {nodes: {__typename: string; createdAt: string}[]}}}
}

function newest(nodes: {__typename: string; createdAt: string}[], types: string[]): string | null {
  return (
    nodes
      .filter(node => types.includes(node.__typename))
      .map(node => node.createdAt)
      .sort()
      .pop() ?? null
  )
}

export function githubApi(token: string, signal: AbortSignal): ReuseApi {
  const client = github.getOctokit(token)
  const {owner, repo} = github.context.repo
  const request = {signal}
  return {
    async filesAt(baseSha, headSha) {
      const response = await client.rest.repos.compareCommitsWithBasehead({
        owner,
        repo,
        basehead: `${baseSha}...${headSha}`,
        per_page: 1,
        request
      })
      const rows = response.data.files ?? []
      return rows.length >= COMPARE_FILE_CAP ? null : rows.flatMap(filesFromApiRow)
    },
    async checkRuns(sha, name) {
      const response = await client.rest.checks.listForRef({
        owner,
        repo,
        ref: sha,
        check_name: name,
        filter: 'latest',
        per_page: 100,
        request
      })
      return response.data.check_runs.map(run => ({
        status: run.status,
        conclusion: run.conclusion,
        startedAt: run.started_at
      }))
    },
    async pullCommits(pullNumber) {
      const commits = await client.paginate(client.rest.pulls.listCommits, {
        owner,
        repo,
        pull_number: pullNumber,
        per_page: 100,
        request
      })
      return commits.map(commit => commit.sha)
    },
    async timeline(pullNumber) {
      const response = await client.graphql<TimelineResponse>(TIMELINE_QUERY, {
        owner,
        name: repo,
        number: pullNumber,
        request
      })
      const nodes = response.repository.pullRequest.timelineItems.nodes
      return {
        readyForReviewAt: newest(nodes, ['ReadyForReviewEvent']),
        baseChangedAt: newest(nodes, ['BaseRefChangedEvent', 'BaseRefForcePushedEvent'])
      }
    },
    async changedOnBranchSince(branch, path, since) {
      const response = await client.rest.repos.listCommits({
        owner,
        repo,
        sha: branch,
        path,
        since,
        per_page: 1,
        request
      })
      return response.data.length > 0
    }
  }
}

async function capture(apiKey: string, decision: Decision): Promise<void> {
  const repo = process.env.GITHUB_REPOSITORY || null
  const pr = decision.pr
  const response = await fetch(`${POSTHOG_HOST}/capture/`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      api_key: apiKey,
      event: EVENT_NAME,
      distinct_id: repo || 'paths-filter-reuse',
      properties: {
        repo,
        reused: decision.reuse,
        reason: decision.reason,
        detail: decision.detail,
        filters: decision.keys,
        previous_sha: decision.previousSha,
        pr_number: pr.number,
        head_sha: pr.head.sha,
        head_ref: pr.head.ref,
        draft: pr.draft,
        duration_ms: decision.durationMs,
        workflow: process.env.GITHUB_WORKFLOW || null,
        job: process.env.GITHUB_JOB || null,
        run_id: process.env.GITHUB_RUN_ID || null,
        run_attempt: process.env.GITHUB_RUN_ATTEMPT || null
      }
    }),
    signal: AbortSignal.timeout(CAPTURE_TIMEOUT_MS)
  })
  if (!response.ok) {
    throw new Error(`capture ${response.status}`)
  }
}

export async function publish(decision: Decision): Promise<void> {
  core.setOutput('reused', decision.reuse)
  core.setOutput('reused_from', decision.previousSha ?? '')
  const filters = decision.keys.join(', ')
  if (decision.reuse) {
    const message = `No file that the ${filters} filters match changed since ${decision.previousSha}, where this workflow passed. Those filters report no changes, so the jobs they gate are skipped and the earlier result stands.`
    core.notice(message, {title: 'Earlier CI result reused'})
    await core.summary
      .addRaw(`**Earlier CI result reused.** ${message}`, true)
      .write()
      .catch(() => undefined)
  } else {
    core.info(`reuse: not reused (${decision.reason}${decision.detail ? `: ${decision.detail}` : ''})`)
  }
  const apiKey = process.env.PATHS_FILTER_REUSE_POSTHOG_TOKEN
  if (apiKey) {
    await capture(apiKey, decision).catch(error => {
      core.info(`reuse: capture skipped (${error instanceof Error ? error.message : String(error)})`)
    })
  }
}
