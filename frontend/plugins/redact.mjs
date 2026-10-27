// Redact replaces React at build time, so it is an environment variable and not a feature flag.
// Redact ships only a Vite plugin. Calling its hooks keeps aliases, stubs and React 18 support upstream.
import { redact } from '@tanstack/redact/vite'
import fs from 'node:fs/promises'
import path from 'node:path'
import { parseAst } from 'vite'

export const isRedactEnabled = process.env.POSTHOG_REACT_RUNTIME === 'redact'

const REACT_SPECIFIER = /^(react|react-dom|scheduler|use-sync-external-store|@tanstack\/redact)(\/.*)?$/
const FEATURE_IMPORT =
    /(^|[\\/])(portal|context|suspense|suspense-runtime|memo|forward-ref|lazy|class|activity|hydration|fragment-refs|view-transition)([\\/]index\.js)?$/
const REDACT_FILE = /[\\/]@tanstack[\\/]redact[\\/]dist[\\/].*\.js$/

export function redactEsbuildPlugin({ root }) {
    const plugins = redact()
    const resolver = plugins.find((plugin) => plugin.name === 'redact')
    const react18 = plugins.find((plugin) => plugin.name === 'redact:react18')
    resolver.configResolved({ root, server: {} })

    const context = {
        environment: { name: 'client' },
        parse: (source) => parseAst(source),
        resolve: async (id, importer) => ({ id: path.resolve(path.dirname(importer), id) }),
    }
    const resolveId = async (id, importer) => {
        const resolved = await resolver.resolveId.call(context, id, importer, {})
        return typeof resolved === 'string' ? { path: resolved } : undefined
    }

    return {
        name: 'redact',
        setup(build) {
            build.onResolve({ filter: REACT_SPECIFIER }, (args) => resolveId(args.path, args.importer))
            build.onResolve({ filter: FEATURE_IMPORT }, (args) =>
                REDACT_FILE.test(args.importer) ? resolveId(args.path, args.importer) : undefined
            )
            if (react18) {
                build.onLoad({ filter: REDACT_FILE }, async (args) => {
                    const source = await fs.readFile(args.path, 'utf8')
                    const result = await react18.transform.call(context, source, args.path)
                    return { contents: result?.code ?? source, loader: 'js' }
                })
            }
        },
    }
}
