// Experimental: swap the React runtime for TanStack Redact (https://tanstack.com/redact) in the app bundles.
// Opt in with REDACT=1. Redact ships only a Vite plugin, so this mirrors its alias table for esbuild.
// esbuild cannot drop Redact's optional features, so this always bundles the full runtime.
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export const isRedactEnabled = ['1', 'true'].includes(process.env.REDACT?.toLowerCase() ?? '')

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

export const REDACT_ALIASES = {
    'use-sync-external-store/shim/with-selector': '@tanstack/redact',
    'use-sync-external-store/shim/with-selector.js': '@tanstack/redact',
    'use-sync-external-store/with-selector': '@tanstack/redact',
    'use-sync-external-store/with-selector.js': '@tanstack/redact',
    'use-sync-external-store/shim': '@tanstack/redact',
    'use-sync-external-store/shim/index.js': '@tanstack/redact',
    'use-sync-external-store': '@tanstack/redact',
    'react/jsx-runtime': '@tanstack/redact/jsx-runtime',
    'react/jsx-dev-runtime': '@tanstack/redact/jsx-dev-runtime',
    'react/compiler-runtime': '@tanstack/redact/compiler-runtime',
    'react-dom/client': '@tanstack/redact/dom-client',
    'react-dom/server': '@tanstack/redact/server',
    'react-dom/server.browser': '@tanstack/redact/server',
    'react-dom/test-utils': '@tanstack/redact/dom-test-utils',
    'react-dom': '@tanstack/redact/dom',
    react: '@tanstack/redact',
    scheduler: '@tanstack/redact/scheduler',
}

const escapeRegExp = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const ALIAS_FILTER = new RegExp(`^(${Object.keys(REDACT_ALIASES).map(escapeRegExp).join('|')})$`)

export function redactEsbuildPlugin() {
    return {
        name: 'redact',
        setup(build) {
            build.onResolve({ filter: ALIAS_FILTER }, (args) =>
                // Resolve from the frontend package so pnpm's per-package node_modules all land on one Redact copy.
                build.resolve(REDACT_ALIASES[args.path], { kind: args.kind, resolveDir: frontendDir })
            )
        },
    }
}
