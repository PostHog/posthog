import { existsSync } from 'node:fs'
import * as path from 'path'
import type { Plugin } from 'vite'

// The app's runtime deps are hoisted to frontend/node_modules, not the repo root.
// Webpack reached them via resolve.modules: [frontend/node_modules]; Vite/Rollup
// has no equivalent. The dev server tolerates the miss, but the production rollup
// build fails to resolve bare imports (e.g. "@posthog/icons") from product files
// whose node_modules chain never reaches frontend/node_modules.
//
// This resolves bare specifiers that exist in frontend/node_modules from there, by
// handing rollup a synthetic importer inside frontend/ so its node resolution walks
// that tree (and its .pnpm symlinks). Specifiers covered by explicit aliases never
// reach this plugin — Vite's alias plugin runs first — and specifiers absent from
// frontend/node_modules fall through to normal resolution.
export function frontendResolvePlugin(frontendDir: string): Plugin {
    const nodeModules = path.resolve(frontendDir, 'node_modules')
    // A real file inside frontend/src so the resolver searches frontend/node_modules.
    // It must exist on disk — Vite's resolver falls back to the wrong root for a
    // non-existent importer, which silently resolves nothing.
    const synthetic = path.join(frontendDir, 'src', 'index.tsx')

    return {
        name: 'frontend-node-modules-resolve',
        enforce: 'pre',
        async resolveId(source, importer, options) {
            if (
                !source ||
                source[0] === '.' ||
                source[0] === '\0' ||
                importer === synthetic ||
                path.isAbsolute(source)
            ) {
                return null
            }
            const parts = source.split('/')
            const pkgDir = source[0] === '@' ? `${parts[0]}/${parts[1]}` : parts[0]
            if (!existsSync(path.join(nodeModules, pkgDir))) {
                return null
            }
            return this.resolve(source, synthetic, { ...options, skipSelf: true })
        },
    }
}
