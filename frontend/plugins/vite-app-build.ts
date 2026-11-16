import { readFileSync } from 'node:fs'
import type { Plugin } from 'vite'

// The esbuild app build loads these extensions as text (the `loader` map in common/esbuilder/utils.mjs).
const TEXT_FILE = /\.(sql|yaml|md)$/

export function textFilesPlugin(): Plugin {
    return {
        name: 'text-files',
        enforce: 'pre',
        load(id) {
            const [file, query] = id.split('?')
            if (query || !TEXT_FILE.test(file)) {
                return null
            }
            return { code: `export default ${JSON.stringify(readFileSync(file, 'utf8'))}`, map: null }
        },
    }
}

// zod re-exports every error-message locale as `z.locales`, and an import that keeps the whole `z`
// object ships all of them. The app uses `en` only. The esbuild build has the same plugin in
// common/esbuilder/utils.mjs.
const ZOD_LOCALES_INDEX = /[\\/]zod[\\/]v4[\\/]locales[\\/]index\.js$/

export function zodEnLocaleOnlyPlugin(): Plugin {
    return {
        name: 'zod-en-locale-only',
        enforce: 'pre',
        load(id) {
            return ZOD_LOCALES_INDEX.test(id.split('?')[0])
                ? { code: 'export { default as en } from "./en.js";', map: null }
                : null
        },
    }
}

// Must match CHUNK_GRAPH_FILE in frontend/bin/viteAppBuild.mjs, which reads this file.
export const CHUNK_GRAPH_FILE = 'vite-app-graph.json'

export function chunkGraphPlugin(): Plugin {
    return {
        name: 'chunk-graph',
        generateBundle(_options, bundle) {
            const chunks = Object.values(bundle).flatMap((output) =>
                output.type === 'chunk'
                    ? [
                          {
                              fileName: output.fileName,
                              name: output.name,
                              imports: output.imports,
                              dynamicImports: output.dynamicImports,
                              exports: output.exports,
                              isEntry: output.isEntry,
                              isDynamicEntry: output.isDynamicEntry,
                              facadeModuleId: output.facadeModuleId,
                              css: [...(output.viteMetadata?.importedCss ?? [])],
                              modules: Object.fromEntries(
                                  Object.entries(output.modules).map(([id, module]) => [id, module.renderedLength])
                              ),
                          },
                      ]
                    : []
            )
            this.emitFile({ type: 'asset', fileName: CHUNK_GRAPH_FILE, source: JSON.stringify(chunks) })
        },
    }
}
