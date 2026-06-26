import { isBuiltin } from 'node:module'
import * as path from 'path'
import type { Plugin } from 'vite'

// Storybook bundles source from several workspaces (the app, quill, the mcp ui-apps)
// but CI installs only @posthog/storybook's dependency closure. So a bare dep can be
// absent from the importer's own node_modules yet present up an installed package's
// chain — e.g. `lucide-react` imported from services/mcp source (aliased in via
// `@posthog/mcp-ui`, and services/mcp is not in the closure) is installed under
// `@posthog/quill`, which the app depends on. The old webpack config papered over
// this with `resolve.modules: [frontend/node_modules, <root>/node_modules,
// 'node_modules']`; Vite/Rollup resolves relative to the importer only.
//
// This resolves bare specifiers from a set of installed "anchor" files (the app and
// quill) before the importer. Each anchor is a real file whose node_modules chain is
// guaranteed installed in CI. First hit wins; if none resolve (the dep lives only in
// the importer's own node_modules, as in a full local install), return null and let
// Vite's normal importer-relative resolution handle it.
//
// Source packages aliased to their checkout (e.g. `@posthog/quill`, `@posthog/mcp-ui`)
// never reach this plugin — Vite's alias plugin runs first.
export function frontendResolvePlugin(repoRoot: string): Plugin {
    // Real files on disk — Vite's resolver falls back to the wrong root for a
    // non-existent importer and silently resolves nothing.
    const anchors = [
        path.join(repoRoot, 'frontend', 'src', 'index.tsx'),
        path.join(repoRoot, 'packages', 'quill', 'packages', 'quill', 'src', 'index.ts'),
    ]

    return {
        name: 'frontend-node-modules-resolve',
        enforce: 'pre',
        async resolveId(source, importer, options) {
            if (
                !source ||
                source[0] === '.' ||
                source[0] === '\0' ||
                anchors.includes(importer as string) ||
                path.isAbsolute(source) ||
                isBuiltin(source)
            ) {
                return null
            }
            for (const anchor of anchors) {
                const resolved = await this.resolve(source, anchor, { ...options, skipSelf: true })
                if (resolved) {
                    return resolved
                }
            }
            return null
        },
    }
}
