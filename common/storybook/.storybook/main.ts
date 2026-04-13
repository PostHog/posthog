import type { StorybookConfig } from '@storybook/types'
import * as fs from 'fs'
import * as path from 'path'
import type { Compiler } from 'webpack'

import { createEntry } from '../webpack.config.js'

/**
 * Emits a minimal module-graph JSON alongside the preview bundle — used by
 * `.github/workflows/ci-storybook.yml`'s shadow-story-selection job (via
 * bin/find-affected-stories.mjs) to compute the set of stories transitively
 * affected by a PR's changed files.
 *
 * We can't use `storybook build --webpack-stats-json` because it emits the
 * full verbose stats (~600 MB, exceeds Node's string size limit). webpack's
 * `stats.toJson()` config is partially overridden by Storybook's builder, so
 * instead we walk the compilation's modulesGraph ourselves and serialize
 * only the fields the analyzer consumes: each module's userRequest-ish name
 * and the userRequest names of modules that import it.
 */
class ModuleGraphPlugin {
    apply(compiler: Compiler): void {
        compiler.hooks.done.tapAsync('ModuleGraphPlugin', (stats, callback) => {
            try {
                const outputPath = compiler.options.output.path
                if (!outputPath) {
                    callback()
                    return
                }
                const compilation = stats.compilation
                // Repo root = three levels up from common/storybook/.storybook (where this
                // file sits); used to strip the absolute prefix from every module path so
                // consumers (bin/find-affected-stories.mjs) work with repo-relative names
                // identical to what `git diff --name-only` produces.
                const repoRoot = path.resolve(__dirname, '..', '..', '..') + path.sep
                const toRelative = (absolute: string): string => {
                    if (absolute.startsWith(repoRoot)) {
                        return absolute.slice(repoRoot.length)
                    }
                    return absolute
                }
                const modules: { name: string; reasons: string[] }[] = []
                const nameOf = (m: any): string | undefined => {
                    const raw =
                        m?.resource ??
                        m?.userRequest ??
                        m?.rawRequest ??
                        (typeof m?.identifier === 'function' ? m.identifier() : undefined)
                    if (typeof raw !== 'string') {
                        return undefined
                    }
                    // Strip loader prefixes (e.g. "babel-loader!./foo.ts") and query strings.
                    const stripped = raw.split('!').pop() ?? raw
                    const noQuery = stripped.split('?')[0]
                    // Only emit repo-relative entries — third-party (node_modules, virtual
                    // webpack modules) aren't useful for git-diff lookups.
                    if (!noQuery.startsWith(repoRoot)) {
                        return undefined
                    }
                    return toRelative(noQuery)
                }
                const seenNames = new Set<string>()

                // Flatten concatenated modules so components inlined by webpack's
                // ModuleConcatenationPlugin still appear as distinct entries we can
                // resolve from a git diff.
                const expand = (m: any): any[] => {
                    if (Array.isArray(m?.modules) && m.modules.length > 0) {
                        return m.modules.flatMap(expand)
                    }
                    return [m]
                }

                const resolveReasons = (mod: any): Set<string> => {
                    const reasons = new Set<string>()
                    for (const conn of compilation.moduleGraph.getIncomingConnections(mod)) {
                        const origin = conn.originModule as any
                        if (!origin) {
                            continue
                        }
                        // Map a concatenated inner-module origin back to its wrapper so
                        // reasons point at a node we're also emitting.
                        const outer = origin.rootModule ?? origin
                        const fromName = nameOf(outer) ?? nameOf(origin)
                        if (fromName) {
                            reasons.add(fromName)
                        }
                    }
                    return reasons
                }

                for (const mod of compilation.modules) {
                    for (const inner of expand(mod as any)) {
                        const name = nameOf(inner)
                        if (!name || seenNames.has(name)) {
                            continue
                        }
                        seenNames.add(name)
                        // Reasons belong to the concatenated wrapper, not the inner
                        // modules (inner modules have no incoming connections).
                        const reasons = resolveReasons(mod as any)
                        // If this inner module is distinct from the wrapper, also fold
                        // in reasons from the inner itself (handles mixed cases).
                        if (inner !== mod) {
                            for (const r of resolveReasons(inner)) {
                                reasons.add(r)
                            }
                        }
                        modules.push({ name, reasons: [...reasons] })
                    }
                }

                const outFile = path.join(outputPath, 'module-graph.json')
                fs.writeFileSync(outFile, JSON.stringify({ modules }))
                // eslint-disable-next-line no-console
                console.log(`[ModuleGraphPlugin] wrote ${modules.length} modules to ${outFile}`)
            } catch (err) {
                // Never break the build — the shadow job will detect missing file and bail.
                // eslint-disable-next-line no-console
                console.warn('[ModuleGraphPlugin] failed to emit module graph:', err)
            }
            callback()
        })
    }
}

const config: StorybookConfig = {
    stories: [
        '../../../frontend/src/**/*.stories.@(js|jsx|ts|tsx|mdx)',
        '../../../products/**/frontend/**/*.stories.@(js|jsx|ts|tsx|mdx)',
        '../../../products/**/mcp/**/*.stories.@(js|jsx|ts|tsx|mdx)',
        '../../../common/mosaic/storybook/**/*.stories.@(js|jsx|ts|tsx|mdx)',
    ],

    addons: [
        '@storybook/addon-docs',
        '@storybook/addon-links',
        '@storybook/addon-essentials',
        '@storybook/addon-storysource',
        '@storybook/addon-a11y',
    ],

    staticDirs: [
        'public',
        { from: '../../../frontend/public', to: '/static' },
        { from: '../../../frontend/node_modules/@posthog/hedgehog-mode/assets', to: '/static/hedgehog-mode' },
    ],

    webpackFinal: (config) => {
        const mainConfig = createEntry('main')
        return {
            ...config,
            // Disable filesystem cache in CI to avoid heap OOM during cache shutdown
            // (especially on memory-constrained environments like Cloudflare Pages)
            cache: process.env.CI ? false : { type: 'filesystem' },
            plugins: [...(config.plugins ?? []), new ModuleGraphPlugin()],
            resolve: {
                ...config.resolve,
                extensions: [...config.resolve!.extensions!, ...mainConfig.resolve.extensions],
                alias: { ...config.resolve!.alias, ...mainConfig.resolve.alias },
            },
            module: {
                ...config.module,
                rules: [
                    ...mainConfig.module.rules,
                    ...(config.module?.rules?.filter(
                        (rule: any) => 'test' in rule && rule.test.toString().includes('.mdx')
                    ) ?? []),
                ],
            },
        }
    },

    framework: {
        name: '@storybook/react-webpack5',
        options: { builder: { useSWC: true } },
    },

    build: {
        test: {
            disableSourcemaps: !!process.env.CI,
        },
    },

    docs: {
        autodocs: 'tag',
    },

    typescript: { reactDocgen: 'react-docgen' }, // Shouldn't be needed in Storybook 8
}

export default config
