import {File} from '../../paths-filter/src/file'
import {parseGitDiffOutput} from '../../paths-filter/src/git-diff'
import {REVISION} from './shared-image-releases'

export type GitRunner = (args: string[], deadline?: number, input?: string) => Promise<string>

export async function assertCheckout(revision: string, git: GitRunner): Promise<void> {
  if (!REVISION.test(revision)) throw new Error('Expected full source revision')
  if ((await git(['rev-parse', '--is-shallow-repository'])).trim() !== 'false') {
    throw new Error('Complete executing source history is unavailable')
  }
  if ((await git(['rev-parse', 'HEAD'])).trim() !== revision) throw new Error('Built revision differs from executing checkout')
}

export async function assertFirstParent(older: string, newer: string, git: GitRunner): Promise<void> {
  if (!REVISION.test(older) || !REVISION.test(newer)) throw new Error('Interval requires full source revisions')
  if (older === newer) return
  const history = (await git(['rev-list', '--first-parent', newer, '--not', older])).split('\n').filter(Boolean)
  const last = history[history.length - 1]
  if (!last || (await git(['rev-list', '--parents', '--max-count=1', last])).split(/\s+/)[1] !== older) {
    throw new Error('Frontier is outside the executing first-parent history')
  }
}

export async function intervalFiles(base: string, revision: string, git: GitRunner): Promise<File[]> {
  await assertCheckout(revision, git)
  await assertFirstParent(base, revision, git)
  if (base === revision) return []
  const output = await git(['log', '--first-parent', '--diff-merges=first-parent', '--format=', '--no-renames', '--name-status', '-z', `${base}..${revision}`])
  const normalized = output.split('\0').filter(Boolean).map((token, index) => index % 2 === 0 && token === 'T' ? 'M' : token).join('\0')
  const files = parseGitDiffOutput(normalized)
  if (files.some(file => file.status === undefined)) throw new Error('Unsupported Git change status')
  return files
}
