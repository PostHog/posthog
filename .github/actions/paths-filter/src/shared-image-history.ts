import {execFileSync} from 'child_process'
import {command} from './shared-image-command'
import {File} from './file'
import {intervalFiles} from './shared-image-interval'
import {loadPolicy, Policy} from './shared-image-releases'

export const POLICY_PATH = '.github/shared-image-releases.yaml'
export const ORDERED_ALIAS = /^r([0-9]{12})-([0-9a-f]{6})$/
export const REVISION = /^[0-9a-f]{40}$/
export const DIGEST = /^sha256:[0-9a-f]{64}$/

export interface HistoryBudgets {
  fetchMs: number
  comparisonMs: number
  maxBuffer: number
}

export interface Comparison {
  files: File[]
  policies: (Policy | undefined)[]
}

export class SourceHistory {
  private readonly prepared = new Map<string, Promise<Comparison>>()
  private readonly policies = new Map<string, Policy>()

  constructor(readonly cwd: string, private readonly budgets: HistoryBudgets, private readonly deadline = Infinity) {}

  private git(args: string[], deadline = Date.now() + this.budgets.comparisonMs, input?: string): string {
    const timeout = Math.min(deadline, this.deadline) - Date.now()
    if (timeout <= 0) throw new Error('Source comparison budget exhausted')
    return execFileSync('git', args, {
      cwd: this.cwd, timeout, maxBuffer: this.budgets.maxBuffer, encoding: 'utf8', input,
      env: {...process.env, GIT_NO_LAZY_FETCH: '1'}, stdio: ['pipe', 'pipe', 'pipe']
    })
  }

  verify(revision: string): void {
    const deadline = Date.now() + this.budgets.comparisonMs
    if (!REVISION.test(revision)) throw new Error('Expected full source revision')
    if (this.git(['rev-parse', '--is-shallow-repository'], deadline).trim() !== 'false') throw new Error('Complete source history is unavailable')
    if (this.git(['rev-parse', 'HEAD'], deadline).trim() !== revision) throw new Error('Built revision differs from executing checkout')
  }

  alias(revision: string, deadline = Date.now() + this.budgets.comparisonMs): string {
    if (!REVISION.test(revision)) throw new Error('Expected full source revision')
    const ordinal = this.git(['rev-list', '--first-parent', '--count', revision], deadline).trim()
    if (!/^[1-9][0-9]{0,11}$/.test(ordinal)) throw new Error('Source ordinal is out of range')
    return `r${ordinal.padStart(12, '0')}-${revision.slice(0, 6)}`
  }

  relation(base: string, revision: string): 'equal' | 'older' | 'newer' {
    const deadline = Date.now() + this.budgets.comparisonMs
    if (!REVISION.test(base) || !REVISION.test(revision)) throw new Error('Expected full source revisions')
    if (base === revision) return 'equal'
    const newer = this.alias(base, deadline) > this.alias(revision, deadline) ? base : revision
    const older = newer === base ? revision : base
    const history = this.git(['rev-list', '--first-parent', newer, '--not', older], deadline).split('\n').filter(Boolean)
    const last = history[history.length - 1]
    if (!last || this.git(['rev-list', '--parents', '--max-count=1', last], deadline).split(/\s+/)[1] !== older) {
      throw new Error('Frontier is outside the executing first-parent history')
    }
    return newer === base ? 'older' : 'newer'
  }

  private async fetch(objects: string[], filter: string | undefined, deadline: number): Promise<void> {
    if (!objects.length) return
    await command('git', [
      'fetch', '--no-tags', '--no-recurse-submodules', '--no-write-fetch-head', '--no-auto-maintenance',
      ...(filter ? [`--filter=${filter}`] : []), 'origin', '--stdin'
    ], {
      cwd: this.cwd, timeoutMs: deadline - Date.now(), maxBuffer: this.budgets.maxBuffer,
      env: {GIT_NO_LAZY_FETCH: '1', GIT_TERMINAL_PROMPT: '0'}, input: [...new Set(objects)].join('\n') + '\n'
    })
  }

  private async trees(revisions: string[], fetchDeadline: number): Promise<void> {
    const trees = [...new Set(this.git(['rev-list', '--no-walk', '--no-commit-header', '--format=%T', ...revisions], fetchDeadline).split('\n').filter(Boolean))]
    const missing = (): boolean => {
      if (Date.now() >= fetchDeadline) throw new Error('Source tree fetch budget exhausted')
      if (this.git(['cat-file', '--batch-check=%(objectname) %(objecttype)'], fetchDeadline, trees.join('\n') + '\n')
        .split('\n').some(line => line.endsWith(' missing'))) return true
      const output = execFileSync('git', ['rev-list', '--objects', '--missing=print', '--filter=blob:none', '--stdin'], {
        cwd: this.cwd, timeout: fetchDeadline - Date.now(), maxBuffer: this.budgets.maxBuffer,
        encoding: 'utf8', input: trees.join('\n') + '\n', env: {...process.env, GIT_NO_LAZY_FETCH: '1'},
        stdio: ['pipe', 'pipe', 'pipe']
      })
      return output.split('\n').some(line => line.startsWith('?'))
    }
    if (missing()) await this.fetch(trees, 'blob:none', fetchDeadline)
    if (missing()) throw new Error('Interval trees remain unavailable after bounded fetch')
  }

  private async readPolicies(revisions: string[], fetchDeadline: number): Promise<(Policy | undefined)[]> {
    const blobs = revisions.map(revision => {
      const entry = this.git(['ls-tree', revision, '--', POLICY_PATH], fetchDeadline)
      if (!entry) return undefined
      const match = /^100(?:644|755) blob ([0-9a-f]{40})\t/.exec(entry)
      if (!match) throw new Error(`${revision}:${POLICY_PATH}: expected a regular policy file`)
      return match[1]
    })
    const missing = [...new Set(blobs.filter((blob): blob is string => Boolean(blob)))].filter(blob => {
      try { this.git(['cat-file', '-e', blob], fetchDeadline); return false } catch { return true }
    })
    await this.fetch(missing, undefined, fetchDeadline)
    return blobs.map(blob => {
      if (!blob) return undefined
      let policy = this.policies.get(blob)
      if (!policy) {
        policy = loadPolicy(this.git(['cat-file', 'blob', blob], fetchDeadline))
        this.policies.set(blob, policy)
      }
      return policy
    })
  }

  async current(revision: string): Promise<Policy> {
    const policy = await this.policyAt(revision)
    if (!policy) throw new Error(`${revision}:${POLICY_PATH}: policy is missing`)
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
    const commits = this.git(['rev-list', '--first-parent', revision, '--not', base], fetchDeadline).split('\n').filter(Boolean)
    await this.trees([base, ...commits], fetchDeadline)
    const deadline = Math.min(this.deadline, Date.now() + this.budgets.comparisonMs)
    const changes = this.git([
      'log', '--first-parent', '--diff-merges=first-parent', '--format=%H', `${base}..${revision}`, '--', POLICY_PATH
    ], deadline).split('\n').filter(Boolean).reverse()
    const policies = await this.readPolicies([base, ...changes], fetchDeadline)
    const files = intervalFiles(base, revision, {
      cwd: this.cwd, timeoutMs: deadline - Date.now(), maxBuffer: this.budgets.maxBuffer
    })
    return {files, policies}
  }
}
