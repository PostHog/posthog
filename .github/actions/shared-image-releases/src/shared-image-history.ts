import {command} from './shared-image-command'
import {File, loadPolicy, Policy} from './shared-image'
import {assertCheckout, assertFirstParent, GitRunner, intervalFiles} from './shared-image-interval'
import {POLICY_PATH, REVISION} from './shared-image-releases'

export interface HistoryBudgets {
  fetchMs: number
  comparisonMs: number
  maxBuffer: number
  retryDelaysMs: readonly [number, number]
}

export interface Comparison {
  files: File[]
  policies: (Policy | undefined)[]
}

export class SourceHistory {
  private readonly prepared = new Map<string, Promise<Comparison>>()
  private readonly policies = new Map<string, Policy>()

  constructor(readonly cwd: string, private readonly budgets: HistoryBudgets, private readonly deadline = Infinity, private readonly policyPath = POLICY_PATH) {}

  readonly git: GitRunner = (args, deadline = Date.now() + this.budgets.comparisonMs, input) => command('git', args, {
    cwd: this.cwd, timeoutMs: Math.min(deadline, this.deadline) - Date.now(), maxBuffer: this.budgets.maxBuffer,
    env: {GIT_NO_LAZY_FETCH: '1', GIT_TERMINAL_PROMPT: '0'}, input
  })

  async verify(revision: string): Promise<void> {
    const deadline = Date.now() + this.budgets.comparisonMs
    await assertCheckout(revision, args => this.git(args, deadline))
  }

  async alias(revision: string, deadline = Date.now() + this.budgets.comparisonMs): Promise<string> {
    if (!REVISION.test(revision)) throw new Error('Expected full source revision')
    const ordinal = (await this.git(['rev-list', '--first-parent', '--count', revision], deadline)).trim()
    if (!/^[1-9][0-9]{0,11}$/.test(ordinal)) throw new Error('Source ordinal is out of range')
    return `r${ordinal.padStart(12, '0')}-${revision.slice(0, 6)}`
  }

  async relation(base: string, revision: string): Promise<'equal' | 'older' | 'newer'> {
    const deadline = Date.now() + this.budgets.comparisonMs
    const newer = await this.alias(base, deadline) > await this.alias(revision, deadline) ? base : revision
    const older = newer === base ? revision : base
    await assertFirstParent(older, newer, args => this.git(args, deadline))
    return base === revision ? 'equal' : newer === base ? 'older' : 'newer'
  }

  private async fetch(objects: string[], deadline: number): Promise<void> {
    if (!objects.length) return
    const failures: string[] = []
    const attempts = this.budgets.retryDelaysMs.length + 1
    for (let attempt = 0; attempt < attempts; attempt++) {
      if (attempt > 0) {
        const delay = this.budgets.retryDelaysMs[attempt - 1]
        if (Math.min(deadline, this.deadline) - Date.now() < delay + 3000) {
          failures.push('retries skipped: fetch budget exhausted')
          break
        }
        await new Promise<void>(resolve => setTimeout(resolve, delay))
      }
      try {
        await this.git([
          'fetch', '--no-tags', '--no-recurse-submodules', '--no-write-fetch-head', '--no-auto-maintenance',
          'origin', '--stdin'
        ], deadline, [...new Set(objects)].join('\n') + '\n')
        return
      } catch (error) {
        failures.push(`attempt ${attempt + 1} of ${attempts}: ${String(error)}`)
      }
    }
    throw new Error(failures.join('; '))
  }

  private async trees(revisions: string[], fetchDeadline: number): Promise<void> {
    const trees = [...new Set((await this.git([
      'rev-list', '--no-walk', '--no-commit-header', '--format=%T', '--stdin'
    ], fetchDeadline, revisions.join('\n') + '\n')).split('\n').filter(Boolean))]
    const roots = await this.git(['cat-file', '--batch-check=%(objectname) %(objecttype)'], fetchDeadline, trees.join('\n') + '\n')
    if (roots.split('\n').some(line => line.endsWith(' missing')) ||
      (await this.git(['rev-list', '--objects', '--missing=print', '--filter=blob:none', '--stdin'], fetchDeadline, trees.join('\n') + '\n'))
        .split('\n').some(line => line.startsWith('?'))) {
      throw new Error('The checkout must provide full history with trees')
    }
  }

  private async readPolicies(revisions: string[], fetchDeadline: number): Promise<(Policy | undefined)[]> {
    const blobs: (string | undefined)[] = []
    for (const revision of revisions) {
      const entry = await this.git(['ls-tree', revision, '--', this.policyPath], fetchDeadline)
      if (!entry) { blobs.push(undefined); continue }
      const match = /^100(?:644|755) blob ([0-9a-f]{40})\t/.exec(entry)
      if (!match) throw new Error(`${revision}:${this.policyPath}: expected a regular policy file`)
      blobs.push(match[1])
    }
    const missing: string[] = []
    for (const blob of new Set(blobs)) {
      if (!blob) continue
      try { await this.git(['cat-file', '-e', blob], fetchDeadline) } catch { missing.push(blob) }
    }
    await this.fetch(missing, fetchDeadline)
    const policies: (Policy | undefined)[] = []
    for (const blob of blobs) {
      if (!blob) { policies.push(undefined); continue }
      let policy = this.policies.get(blob)
      if (!policy) {
        policy = loadPolicy(await this.git(['cat-file', 'blob', blob], fetchDeadline))
        this.policies.set(blob, policy)
      }
      policies.push(policy)
    }
    return policies
  }

  async current(revision: string): Promise<Policy> {
    const policy = await this.policyAt(revision)
    if (!policy) throw new Error(`${revision}:${this.policyPath}: policy is missing`)
    return policy
  }

  async policyAt(revision: string): Promise<Policy | undefined> {
    const deadline = Math.min(this.deadline, Date.now() + this.budgets.fetchMs)
    await this.trees([revision], deadline)
    const [policy] = await this.readPolicies([revision], deadline)
    return policy
  }

  compare(base: string, revision: string): Promise<Comparison> {
    const key = `${base}/${revision}`
    let result = this.prepared.get(key)
    if (!result) {
      result = this.prepare(base, revision)
      this.prepared.set(key, result)
    }
    return result
  }

  private async prepare(base: string, revision: string): Promise<Comparison> {
    const fetchDeadline = Math.min(this.deadline, Date.now() + this.budgets.fetchMs)
    const commits = (await this.git(['rev-list', '--first-parent', revision, '--not', base], fetchDeadline)).split('\n').filter(Boolean)
    await this.trees([base, ...commits], fetchDeadline)
    const changes = (await this.git([
      'log', '--first-parent', '--diff-merges=first-parent', '--no-patch', '--format=%H', `${base}..${revision}`, '--', this.policyPath
    ], fetchDeadline)).split('\n').filter(Boolean).reverse()
    const policies = await this.readPolicies([base, ...changes], fetchDeadline)
    const deadline = Math.min(this.deadline, Date.now() + this.budgets.comparisonMs)
    const files = await intervalFiles(base, revision, args => this.git(args, deadline))
    return {files, policies}
  }
}
