import {execFile} from 'child_process'
import * as os from 'os'
import * as path from 'path'

import * as core from '@actions/core'
import {PullRequest} from '@octokit/webhooks-types'

import {File} from './file'
import {Filter, FilterResults, firedKeys} from './filter'
import {parseGitDiffOutput} from './git'

// Compares the API's changed-file list against the same list derived from the pull
// request's merge commit, and reports disagreement without acting on it. The API
// result stays authoritative, so a wrong local answer can only produce a log line.

const MERGE_REF_FETCH_DEPTH = 2
const POSTHOG_HOST = 'https://us.i.posthog.com'
const EVENT_NAME = 'paths_filter_shadow_compared'

// A change-detection job is on the critical path of every workflow, so the comparison
// and its capture share one wall-clock budget rather than holding the job to its
// timeout-minutes.
const BUDGET_MS = 20000
const CAPTURE_FLOOR_MS = 500
const LIST_CAP = 50

// A queue branch carries the cumulative batch diff, which execFile's 1 MB default would
// fail as a diff error.
const MAX_GIT_OUTPUT_BYTES = 64 * 1024 * 1024
const DETAIL_CAP = 200

type Verdict = 'match' | 'mismatch' | 'unavailable'

// Closed, because this is the field the events are grouped by. Git's own words go in
// `detail`, which is unbounded.
type Reason =
  | 'no-scratch-repo'
  | 'no-origin-url'
  | 'no-merge-ref'
  | 'no-second-parent'
  | 'stale-merge-ref'
  | 'diff-failed'
  | 'budget-exceeded'
  | 'unknown'

class Unavailable extends Error {
  constructor(readonly reason: Reason, readonly detail: string) {
    super(`${reason}: ${detail}`)
  }
}

interface Difference {
  count: number
  sample: string[]
}

interface ShadowResult {
  verdict: Verdict
  reason: Reason | null
  detail: string | null
  apiCount: number
  gitCount: number | null
  onlyInApi: Difference
  onlyInGit: Difference
  keysLost: string[]
  keysGained: string[]
}

export interface ShadowInput {
  filter: Filter
  apiFiles: File[]
  apiResults: FilterResults
  apiRows: number
  apiTruncated: boolean
  pr: PullRequest
}

interface GitResult {
  code: number
  out: string
  err: string
}

// `--depth` and `--filter` rewrite `.git/shallow` and the promisor config of whatever
// repository they run in, so every call names the scratch repository. ci-dagster and
// ci-e2e-playwright read history from the workspace checkout after this action returns.
async function git(gitDir: string, args: string[], signal: AbortSignal): Promise<GitResult> {
  return run(['--git-dir', gitDir, ...args], signal)
}

// execFile rather than `@actions/exec`, which gives no handle on the child process, so a
// fetch the budget gave up on would hold the action open until it finished. stdout is
// returned raw because a tracked path can begin with a space.
async function run(args: string[], signal: AbortSignal): Promise<GitResult> {
  return new Promise(resolve => {
    execFile('git', args, {signal, maxBuffer: MAX_GIT_OUTPUT_BYTES}, (error, stdout, stderr) => {
      resolve({code: error ? 1 : 0, out: stdout, err: stderr.trim()})
    })
  })
}

function firstLine(stderr: string): string {
  return stderr.slice(0, DETAIL_CAP).split('\n')[0] || 'no stderr'
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function missing(from: Set<string>, against: Set<string>): string[] {
  return [...from].filter(key => !against.has(key)).sort()
}

async function scratchRepo(signal: AbortSignal): Promise<string> {
  const gitDir = path.join(process.env.RUNNER_TEMP || os.tmpdir(), 'paths-filter-shadow.git')
  const init = await run(['init', '--bare', '--quiet', gitDir], signal)
  if (init.code !== 0) {
    throw new Unavailable('no-scratch-repo', firstLine(init.err))
  }
  return gitDir
}

// actions/checkout keeps the token in an http.extraheader the scratch repository does not
// inherit, so a private remote reports unavailable rather than comparing a partial fetch.
function originUrl(): string {
  const server = process.env.GITHUB_SERVER_URL
  const repo = process.env.GITHUB_REPOSITORY
  if (!server || !repo) {
    throw new Unavailable('no-origin-url', 'GITHUB_SERVER_URL or GITHUB_REPOSITORY is unset')
  }
  return `${server}/${repo}`
}

async function localChangedFiles(pr: PullRequest, signal: AbortSignal): Promise<File[]> {
  const gitDir = await scratchRepo(signal)

  const fetched = await git(
    gitDir,
    [
      '-c',
      'http.lowSpeedLimit=1000',
      '-c',
      'http.lowSpeedTime=10',
      'fetch',
      '--no-tags',
      '--filter=blob:none',
      `--depth=${MERGE_REF_FETCH_DEPTH}`,
      originUrl(),
      `refs/pull/${pr.number}/merge`
    ],
    signal
  )
  if (fetched.code !== 0) {
    throw new Unavailable('no-merge-ref', firstLine(fetched.err))
  }

  const head = await git(gitDir, ['rev-parse', 'FETCH_HEAD^2'], signal)
  if (head.code !== 0) {
    throw new Unavailable('no-second-parent', firstLine(head.err))
  }
  // GitHub recomputes the merge ref asynchronously after a push, so a ref whose second
  // parent is not the head SHA describes an earlier push.
  const headSha = head.out.trim()
  if (headSha !== pr.head.sha) {
    throw new Unavailable('stale-merge-ref', `^2=${headSha.slice(0, 8)}, head=${pr.head.sha.slice(0, 8)}`)
  }

  // The same flags the action's own git path uses, so the comparison measures what
  // dropping the API call would select. --no-renames matches the add-plus-delete shape
  // the API path builds from `previous_filename`.
  const diff = await git(gitDir, ['diff', '--no-renames', '--name-status', '-z', 'FETCH_HEAD^1', 'FETCH_HEAD'], signal)
  if (diff.code !== 0) {
    throw new Unavailable('diff-failed', firstLine(diff.err))
  }
  return parseGitDiffOutput(diff.out)
}

function difference(from: Set<string>, against: Set<string>): Difference {
  const sample: string[] = []
  let count = 0
  for (const filename of from) {
    if (against.has(filename)) {
      continue
    }
    count++
    if (sample.length < LIST_CAP) {
      sample.push(filename)
    }
  }
  return {count, sample}
}

function compare(input: ShadowInput, api: Set<string>, gitFiles: File[]): ShadowResult {
  const local = new Set(gitFiles.map(f => f.filename))
  const onlyInApi = difference(api, local)
  const onlyInGit = difference(local, api)
  const apiKeys = firedKeys(input.apiResults)
  const gitKeys = firedKeys(input.filter.match(gitFiles))
  return {
    verdict: onlyInApi.count === 0 && onlyInGit.count === 0 ? 'match' : 'mismatch',
    reason: null,
    detail: null,
    apiCount: api.size,
    gitCount: local.size,
    onlyInApi,
    onlyInGit,
    keysLost: missing(apiKeys, gitKeys),
    keysGained: missing(gitKeys, apiKeys)
  }
}

async function budgeted<T>(work: (signal: AbortSignal) => Promise<T>, ms: number): Promise<T> {
  const controller = new AbortController()
  let timer: NodeJS.Timeout
  const expiry = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      controller.abort()
      reject(new Unavailable('budget-exceeded', `${ms}ms`))
    }, ms)
  })
  return Promise.race([work(controller.signal), expiry]).finally(() => clearTimeout(timer))
}

export async function compareWithMergeCommit(input: ShadowInput): Promise<ShadowResult> {
  const api = new Set(input.apiFiles.map(f => f.filename))
  try {
    const gitFiles = await budgeted(async signal => localChangedFiles(input.pr, signal), BUDGET_MS)
    return compare(input, api, gitFiles)
  } catch (error) {
    return {
      verdict: 'unavailable',
      reason: error instanceof Unavailable ? error.reason : 'unknown',
      detail: error instanceof Unavailable ? error.detail : messageOf(error),
      apiCount: api.size,
      gitCount: null,
      onlyInApi: {count: 0, sample: []},
      onlyInGit: {count: 0, sample: []},
      keysLost: [],
      keysGained: []
    }
  }
}

async function capture(apiKey: string, input: ShadowInput, result: ShadowResult, durationMs: number): Promise<void> {
  const repo = process.env.GITHUB_REPOSITORY || null
  const pr = input.pr
  const properties = {
    repo,
    verdict: result.verdict,
    reason: result.reason,
    detail: result.detail,
    api_count: result.apiCount,
    git_count: result.gitCount,
    only_in_api: result.onlyInApi.sample,
    only_in_api_count: result.onlyInApi.count,
    only_in_git: result.onlyInGit.sample,
    only_in_git_count: result.onlyInGit.count,
    selection_changed: result.keysLost.length > 0 || result.keysGained.length > 0,
    keys_lost: result.keysLost,
    keys_gained: result.keysGained,
    // `pr_changed_files` reads stale on a pull request whose base moved, so it is
    // recorded beside the API's own row count rather than used as the truncation tell.
    api_rows: input.apiRows,
    api_truncated: input.apiTruncated,
    pr_changed_files: pr.changed_files,
    pr_number: pr.number,
    head_sha: pr.head.sha,
    head_ref: pr.head.ref,
    base_ref: pr.base.ref,
    branch_class: pr.head.ref.startsWith('trunk-merge/') ? 'trunk-merge' : 'pull-request',
    is_fork: pr.head.repo?.full_name !== repo,
    duration_ms: durationMs,
    workflow: process.env.GITHUB_WORKFLOW || null,
    job: process.env.GITHUB_JOB || null,
    run_id: process.env.GITHUB_RUN_ID || null,
    run_attempt: process.env.GITHUB_RUN_ATTEMPT || null
  }
  const res = await fetch(`${POSTHOG_HOST}/capture/`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      api_key: apiKey,
      event: EVENT_NAME,
      distinct_id: repo || 'paths-filter-shadow',
      properties
    }),
    signal: AbortSignal.timeout(Math.max(CAPTURE_FLOOR_MS, BUDGET_MS - durationMs))
  })
  if (!res.ok) {
    throw new Error(`capture ${res.status}`)
  }
}

function summarize(result: ShadowResult): string {
  if (result.verdict === 'unavailable') {
    return `unavailable (${result.reason}: ${result.detail})`
  }
  if (result.verdict === 'mismatch') {
    return (
      `MISMATCH api=${result.apiCount} git=${result.gitCount} ` +
      `onlyInApi=${JSON.stringify(result.onlyInApi.sample)} onlyInGit=${JSON.stringify(result.onlyInGit.sample)} ` +
      `keysLost=${JSON.stringify(result.keysLost)} keysGained=${JSON.stringify(result.keysGained)}`
    )
  }
  return `match (${result.apiCount} files)`
}

// Never throws: the filter's real answer is already computed by the time this runs. The
// token gates the comparison itself, so a run that cannot record its result does not pay
// for a merge-ref fetch. Fork pull requests get no secrets and take that path too.
export async function report(input: ShadowInput): Promise<void> {
  const apiKey = process.env.PATHS_FILTER_SHADOW_POSTHOG_TOKEN
  if (!apiKey) {
    return
  }
  try {
    core.startGroup('Shadow: merge-commit change detection')
    const startedAt = Date.now()
    const result = await compareWithMergeCommit(input)
    const durationMs = Date.now() - startedAt

    // core.info even for a mismatch, because a warning becomes an annotation on the
    // checks page and reads as a problem with the pull request.
    core.info(`shadow: ${summarize(result)} in ${durationMs}ms`)

    await capture(apiKey, input, result, durationMs).catch(error => {
      core.info(`shadow: capture skipped (${messageOf(error)})`)
    })
  } catch (error) {
    core.info(`shadow: skipped (${messageOf(error)})`)
  } finally {
    core.endGroup()
  }
}
