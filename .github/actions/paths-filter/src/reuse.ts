import * as core from '@actions/core'
import * as github from '@actions/github'
import {PullRequest} from '@octokit/webhooks-types'

import {ChangeStatus, File, filesFromApiRow} from './file'
import {Filter, FilterResults} from './filter'

const BUDGET_MS = 20000
const CAPTURE_TIMEOUT_MS = 2000
const COMPARE_FILE_CAP = 300
const MAX_EARLIER_HEADS = 30
const FINGERPRINT_PATHS = 5
const MAX_SOURCE_AGE_MS = 24 * 60 * 60 * 1000
const DETAIL_SAMPLE = 5
const NULL_SHA = '0000000000000000000000000000000000000000'
const POSTHOG_HOST = 'https://us.i.posthog.com'
const EVENT_NAME = 'posthog-ci-reuse-decision'
const MERGE_QUEUE_BRANCH_PREFIX = 'trunk-merge/'
const PASSING_CONCLUSIONS = ['success', 'skipped']
const INCONCLUSIVE_CONCLUSIONS = ['cancelled', 'stale']
const DEFAULT_CHECK_APPS = ['github-actions']
const TREES_PER_QUERY = 100

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
  | 'shared-head'
  | 'filter-changed'
  | 'budget-exceeded'
  | 'error'

export interface ReuseConfig {
  checks: string[]
  proofChecks: string[]
  checkApps: string[]
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
  app: string | null
  suiteCreatedAt: string | null
}

export interface PullTimeline {
  readyForReviewAt: string | null
  baseChangedAt: string | null
}

export interface ReuseApi {
  filesAt(baseSha: string, headSha: string): Promise<File[] | null>
  checkRuns(sha: string, name: string): Promise<CheckRun[]>
  modes(sha: string, paths: string[]): Promise<Map<string, number | null>>
  branchHeads(branch: string): Promise<string[]>
  blobs(shas: string[], paths: string[]): Promise<Map<string, (string | null)[]>>
  pullsWithCommit(sha: string): Promise<number[]>
  timeline(pullNumber: number): Promise<PullTimeline>
  changedOnBranchSince(branch: string, path: string, since: string): Promise<boolean>
}

export interface Decision {
  reuse: boolean
  reason: Reason
  detail: string | null
  previousSha: string | null
  earlierHeads: number | null
  headsBehind: number | null
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
    checkApps: listInput('reuse-check-apps').length > 0 ? listInput('reuse-check-apps') : DEFAULT_CHECK_APPS,
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

type Verdict = Pick<Decision, 'reuse' | 'reason' | 'detail' | 'previousSha' | 'earlierHeads' | 'headsBehind'>

function miss(reason: Reason, detail: string | null = null, earlierHeads: number | null = null): Verdict {
  return {reuse: false, reason, detail, previousSha: null, earlierHeads, headsBehind: null}
}

interface ProvenRun {
  sha: string
  startedAt: string
  earlierHeads: number | null
  headsBehind: number
}

interface EarlierHeads {
  shas: string[]
  listed: number | null
}

async function differingFrom(
  input: ReuseInput,
  api: ReuseApi,
  current: Map<string, string>,
  sha: string
): Promise<string[] | Verdict> {
  const previousFiles = await api.filesAt(input.pr.base.sha, sha)
  if (previousFiles === null) {
    return miss('file-list-truncated', sha)
  }
  const previous = inputsOf(input.filter, input.config, previousFiles)
  if (previous === null) {
    return miss('error', `a file at ${sha} has no blob sha`)
  }
  return differingFiles(current, previous)
}

async function earlierHeads(input: ReuseInput, api: ReuseApi, before: string): Promise<EarlierHeads> {
  const {head} = input.pr
  let listed: string[] | null = null
  try {
    listed = await api.branchHeads(head.ref)
  } catch (error) {
    core.info(`reuse: branch activity unavailable (${error instanceof Error ? error.message : String(error)})`)
  }
  const older = (listed ?? []).slice((listed ?? []).indexOf(head.sha) + 1)
  const shas = [...new Set([before, ...older])].filter(sha => isSha(sha) && sha !== head.sha)
  return {shas: shas.slice(0, MAX_EARLIER_HEADS), listed: listed === null ? null : shas.length}
}

async function headsWithSameContent(
  input: ReuseInput,
  api: ReuseApi,
  heads: string[],
  before: string,
  differingFromBefore: string[],
  current: Map<string, string>
): Promise<string[]> {
  const others = heads.filter(sha => sha !== before)
  const beforeMatches = differingFromBefore.length === 0
  if (others.length === 0) {
    return beforeMatches ? [before] : []
  }
  const paths = [...new Set([...differingFromBefore, ...current.keys()])].slice(0, FINGERPRINT_PATHS)
  let blobs: Map<string, (string | null)[]>
  try {
    blobs = await api.blobs([input.pr.head.sha, ...others], paths)
  } catch (error) {
    core.info(`reuse: earlier head contents unavailable (${error instanceof Error ? error.message : String(error)})`)
    return beforeMatches ? [before] : []
  }
  const now = JSON.stringify(blobs.get(input.pr.head.sha))
  const matching = new Set(others.filter(sha => JSON.stringify(blobs.get(sha)) === now))
  return heads.filter(sha => (sha === before ? beforeMatches : matching.has(sha)))
}

async function checkRunsFrom(input: ReuseInput, api: ReuseApi, sha: string, names: string[]): Promise<CheckRun[][]> {
  const lists = await Promise.all(names.map(async name => api.checkRuns(sha, name)))
  return lists.map(runs => runs.filter(run => run.app !== null && input.config.checkApps.includes(run.app)))
}

function earliestSuite(runs: CheckRun[]): string | null {
  const created = runs.flatMap(run => (run.suiteCreatedAt ? [run.suiteCreatedAt] : [])).sort()
  return created.length === runs.length ? created[0] : null
}

function isPassing(run: CheckRun): boolean {
  return PASSING_CONCLUSIONS.includes(run.conclusion ?? '')
}

function isFailure(run: CheckRun): boolean {
  return run.status === 'completed' && !isPassing(run) && !INCONCLUSIVE_CONCLUSIONS.includes(run.conclusion ?? '')
}

function firstFailure(config: ReuseConfig, shas: string[], gatesByHead: CheckRun[][][]): string | null {
  for (const [index, gates] of gatesByHead.entries()) {
    const failedGate = gates.findIndex(runs => runs.some(isFailure))
    if (failedGate >= 0) {
      const failed = gates[failedGate].find(isFailure)
      return `${shas[index]} ${config.checks[failedGate]}: ${failed?.conclusion}`
    }
  }
  return null
}

async function proveRun(
  input: ReuseInput,
  api: ReuseApi,
  current: Map<string, string>,
  before: string
): Promise<ProvenRun | Verdict> {
  const {config} = input
  const differingFromBefore = await differingFrom(input, api, current, before)
  if (!Array.isArray(differingFromBefore)) {
    return differingFromBefore
  }
  const heads = await earlierHeads(input, api, before)
  const candidates = await headsWithSameContent(input, api, heads.shas, before, differingFromBefore, current)
  let unchecked = 0
  for (const sha of candidates) {
    if (sha !== before) {
      const differing = await differingFrom(input, api, current, sha)
      if (!Array.isArray(differing)) {
        return {...differing, earlierHeads: heads.listed}
      }
      if (differing.length > 0) {
        continue
      }
    }
    const position = heads.shas.indexOf(sha)
    const newer = heads.shas.slice(unchecked, position)
    unchecked = position + 1
    const [gates, proofs, newerGates] = await Promise.all([
      checkRunsFrom(input, api, sha, config.checks),
      checkRunsFrom(input, api, sha, config.proofChecks),
      Promise.all(newer.map(async other => checkRunsFrom(input, api, other, config.checks)))
    ])
    const failure = firstFailure(config, [...newer, sha], [...newerGates, gates])
    if (failure) {
      return miss('previous-not-green', failure, heads.listed)
    }
    const allGatesPassed = gates.every(runs => runs.length > 0 && runs.every(isPassing))
    const proof = allGatesPassed ? proofs.flat().find(run => run.conclusion === 'success') : undefined
    if (!proof) {
      continue
    }
    const startedAt = earliestSuite([...gates.flat(), proof])
    return startedAt
      ? {sha, startedAt, earlierHeads: heads.listed, headsBehind: position}
      : miss('error', `${sha}: a check run has no check suite time`, heads.listed)
  }
  return differingFromBefore.length > 0
    ? miss('inputs-changed', differingFromBefore.slice(0, DETAIL_SAMPLE).join(', '), heads.listed)
    : miss('no-proven-run', null, heads.listed)
}

async function changedModes(
  input: ReuseInput,
  api: ReuseApi,
  current: Map<string, string>,
  sha: string
): Promise<string[]> {
  const paths = [...current].filter(([, identity]) => identity !== ChangeStatus.Deleted).map(([path]) => path)
  if (paths.length === 0) {
    return []
  }
  const [now, then] = await Promise.all([api.modes(input.pr.head.sha, paths), api.modes(sha, paths)])
  return paths.filter(path => (now.get(path) ?? null) !== (then.get(path) ?? null))
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
  const proven = await proveRun(input, api, current, before)
  if ('reason' in proven) {
    return proven
  }
  const missed = (reason: Reason, detail: string | null): Verdict => miss(reason, detail, proven.earlierHeads)
  if (proven.startedAt < pr.created_at) {
    return missed('shared-head', `${proven.sha} ran before #${pr.number} was opened`)
  }
  const otherPulls = (await api.pullsWithCommit(proven.sha)).filter(number => number !== pr.number)
  if (otherPulls.length > 0) {
    return missed('shared-head', `${proven.sha} is also in ${otherPulls.map(number => `#${number}`).join(', ')}`)
  }
  const modeChanges = await changedModes(input, api, current, proven.sha)
  if (modeChanges.length > 0) {
    return missed('inputs-changed', `mode of ${modeChanges.slice(0, DETAIL_SAMPLE).join(', ')}`)
  }
  if (Date.parse(proven.startedAt) > input.now) {
    return missed('error', `${proven.sha} started in the future, at ${proven.startedAt}`)
  }
  if (input.now - Date.parse(proven.startedAt) > MAX_SOURCE_AGE_MS) {
    return missed('previous-too-old', `${proven.sha} started ${proven.startedAt}`)
  }
  const timeline = await api.timeline(pr.number)
  if (!pr.draft && timeline.readyForReviewAt !== null && proven.startedAt < timeline.readyForReviewAt) {
    return missed('previous-ran-as-draft', proven.sha)
  }
  if (timeline.baseChangedAt !== null && timeline.baseChangedAt > proven.startedAt) {
    return missed('base-changed', timeline.baseChangedAt)
  }
  if (await api.changedOnBranchSince(pr.base.ref, config.filterSource, proven.startedAt)) {
    return missed('filter-changed', config.filterSource)
  }
  return {
    reuse: true,
    reason: 'reused',
    detail: null,
    previousSha: proven.sha,
    earlierHeads: proven.earlierHeads,
    headsBehind: proven.headsBehind
  }
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
    controller.abort()
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

interface TreeEntry {
  name: string
  mode: number
}

type TreesResponse = {repository: Record<string, {entries?: TreeEntry[]} | null>}

type BlobsResponse = {repository: Record<string, {oid: string} | null>}

function directoryOf(path: string): string {
  const slash = path.lastIndexOf('/')
  return slash < 0 ? '' : path.slice(0, slash)
}

function baseNameOf(path: string): string {
  return path.slice(path.lastIndexOf('/') + 1)
}

export function githubApi(token: string, signal: AbortSignal): ReuseApi {
  const client = github.getOctokit(token)
  const {owner, repo} = github.context.repo
  const request = {signal}
  const suites = new Map<string, Promise<Map<number, string>>>()

  async function suiteCreatedAt(sha: string): Promise<Map<number, string>> {
    let created = suites.get(sha)
    if (!created) {
      created = client
        .paginate(client.rest.checks.listSuitesForRef, {owner, repo, ref: sha, per_page: 100, request})
        .then(rows => new Map(rows.map(suite => [suite.id, suite.created_at ?? ''])))
      suites.set(sha, created)
    }
    return created
  }

  async function trees(sha: string, directories: string[]): Promise<Map<string, TreeEntry[]>> {
    const variables: Record<string, unknown> = {owner, name: repo, request}
    const fields = directories.map((directory, index) => {
      variables[`e${index}`] = `${sha}:${directory}`
      return `t${index}: object(expression: $e${index}) { ... on Tree { entries { name mode } } }`
    })
    const declarations = directories.map((_, index) => `$e${index}: String!`).join(', ')
    const response = await client.graphql<TreesResponse>(
      `query ($owner: String!, $name: String!, ${declarations}) { repository(owner: $owner, name: $name) { ${fields.join(
        ' '
      )} } }`,
      variables
    )
    return new Map(directories.map((directory, index) => [directory, response.repository[`t${index}`]?.entries ?? []]))
  }

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
      const created = await suiteCreatedAt(sha)
      return response.data.check_runs.map(run => ({
        status: run.status,
        conclusion: run.conclusion,
        app: run.app?.slug ?? null,
        suiteCreatedAt: (run.check_suite && created.get(run.check_suite.id)) || null
      }))
    },
    async modes(sha, paths) {
      const directories = [...new Set(paths.map(directoryOf))]
      const chunks = Array.from({length: Math.ceil(directories.length / TREES_PER_QUERY)}, (_, index) =>
        directories.slice(index * TREES_PER_QUERY, (index + 1) * TREES_PER_QUERY)
      )
      const listings = new Map(
        (await Promise.all(chunks.map(async chunk => trees(sha, chunk)))).flatMap(listing => [...listing])
      )
      return new Map(
        paths.map(path => [
          path,
          listings.get(directoryOf(path))?.find(entry => entry.name === baseNameOf(path))?.mode ?? null
        ])
      )
    },
    async branchHeads(branch) {
      const response = await client.rest.repos.listActivities({
        owner,
        repo,
        ref: `refs/heads/${branch}`,
        time_period: 'day',
        per_page: 100,
        request
      })
      return response.data.map(activity => activity.after)
    },
    async blobs(shas, paths) {
      const variables: Record<string, unknown> = {owner, name: repo, request}
      const names: string[] = []
      const fields = shas.flatMap((sha, s) =>
        paths.map((path, p) => {
          names.push(`e${s}_${p}`)
          variables[`e${s}_${p}`] = `${sha}:${path}`
          return `b${s}_${p}: object(expression: $e${s}_${p}) { oid }`
        })
      )
      const declarations = names.map(name => `$${name}: String!`).join(', ')
      const response = await client.graphql<BlobsResponse>(
        `query ($owner: String!, $name: String!, ${declarations}) { repository(owner: $owner, name: $name) { ${fields.join(
          ' '
        )} } }`,
        variables
      )
      return new Map(shas.map((sha, s) => [sha, paths.map((_, p) => response.repository[`b${s}_${p}`]?.oid ?? null)]))
    },
    async pullsWithCommit(sha) {
      const response = await client.rest.repos.listPullRequestsAssociatedWithCommit({
        owner,
        repo,
        commit_sha: sha,
        per_page: 100,
        request
      })
      return response.data.map(pull => pull.number)
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
        earlier_heads: decision.earlierHeads,
        heads_behind: decision.headsBehind,
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
