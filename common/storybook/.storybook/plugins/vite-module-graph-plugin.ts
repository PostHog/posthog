import { execFileSync } from 'child_process'
import * as path from 'path'
import type { Plugin } from 'vite'

/**
 * Emits a minimal module-graph JSON alongside the built preview bundle — consumed
 * by `.github/workflows/ci-storybook.yml`'s story-selection job (via
 * bin/find-affected-stories) to compute the set of stories transitively affected
 * by a PR's changed files.
 *
 * The Vite/Rollup port of the former webpack `ModuleGraphPlugin`. Rollup already
 * tracks the full graph, so we just serialize each module's repo-relative path and
 * the repo-relative paths of its importers (`reasons`, matching the old format the
 * analyzer reads: `{ modules: [{ name, reasons }] }`).
 */
export function moduleGraphPlugin(repoRoot: string): Plugin {
    const repoRootWithSep = repoRoot.endsWith(path.sep) ? repoRoot : repoRoot + path.sep

    // Tracked + untracked-but-not-ignored paths, so we drop node_modules / build
    // outputs the consumer (which diffs against `git diff --name-only`) never sees.
    // Null = couldn't ask git, skip filtering.
    const loadGitTrackedPaths = (): Set<string> | null => {
        try {
            const stdout = execFileSync('git', ['ls-files', '--cached', '--others', '--exclude-standard'], {
                encoding: 'utf-8',
                cwd: repoRootWithSep,
                maxBuffer: 128 * 1024 * 1024,
            })
            return new Set(stdout.split('\n').filter(Boolean))
        } catch (err) {
            // eslint-disable-next-line no-console
            console.warn('[module-graph] git ls-files failed, skipping gitignore filter:', err)
            return null
        }
    }

    return {
        name: 'posthog-storybook-module-graph',
        apply: 'build',
        generateBundle() {
            const gitTracked = loadGitTrackedPaths()
            // Map a Rollup module id to a repo-relative, git-tracked path (or undefined
            // for node_modules / virtual modules the analyzer can't resolve from a diff).
            const nameOf = (id: string): string | undefined => {
                const noQuery = id.split('?')[0]
                if (!noQuery.startsWith(repoRootWithSep)) {
                    return undefined
                }
                const relative = noQuery.slice(repoRootWithSep.length)
                if (gitTracked && !gitTracked.has(relative)) {
                    return undefined
                }
                return relative
            }

            const modules: { name: string; reasons: string[] }[] = []
            for (const id of this.getModuleIds()) {
                const name = nameOf(id)
                if (!name) {
                    continue
                }
                const info = this.getModuleInfo(id)
                const reasons = new Set<string>()
                const importers = new Set<string>([...(info?.importers ?? []), ...(info?.dynamicImporters ?? [])])
                for (const importer of importers) {
                    const from = nameOf(importer)
                    if (from) {
                        reasons.add(from)
                    }
                }
                modules.push({ name, reasons: [...reasons] })
            }

            this.emitFile({ type: 'asset', fileName: 'module-graph.json', source: JSON.stringify({ modules }) })
            // eslint-disable-next-line no-console
            console.log(`[module-graph] wrote ${modules.length} modules to module-graph.json`)
        },
    }
}
