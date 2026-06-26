import { isBuiltin } from 'node:module'
import * as path from 'path'
import type { Plugin } from 'vite'

// The app's runtime deps are hoisted to frontend/node_modules (and the repo root),
// not into every workspace that Storybook bundles. The old webpack config reached
// them with `resolve.modules: [frontend/node_modules, <repo root>/node_modules,
// 'node_modules']` — searching the frontend/root chain BEFORE the importer's own
// node_modules. Vite/Rollup has no equivalent: it resolves bare imports relative to
// the importer, so a package like `lucide-react` imported from `services/mcp` source
// (aliased in via `@posthog/mcp-ui`) fails in CI, where `services/mcp` itself isn't
// installed but the dep is present up the frontend chain.
//
// This ports that behavior: resolve every bare specifier from a real file in
// frontend/src first (Node resolution walks frontend/node_modules then the repo
// root). If found, use it — matching webpack's frontend-first ordering. If not (the
// dep only exists in the importer's own node_modules, as in a full local install),
// return null and let Vite's normal importer-relative resolution handle it.
//
// Source packages aliased to their checkout (e.g. `@posthog/quill`, `@posthog/mcp-ui`)
// never reach this plugin — Vite's alias plugin runs first.
export function frontendResolvePlugin(frontendDir: string): Plugin {
    // A real file inside frontend/src so resolution searches frontend/node_modules and
    // up to the repo root. It must exist on disk — Vite's resolver falls back to the
    // wrong root for a non-existent importer and silently resolves nothing.
    const base = path.join(frontendDir, 'src', 'index.tsx')

    return {
        name: 'frontend-node-modules-resolve',
        enforce: 'pre',
        async resolveId(source, importer, options) {
            if (
                !source ||
                source[0] === '.' ||
                source[0] === '\0' ||
                importer === base ||
                path.isAbsolute(source) ||
                isBuiltin(source)
            ) {
                return null
            }
            return this.resolve(source, base, { ...options, skipSelf: true })
        },
    }
}
