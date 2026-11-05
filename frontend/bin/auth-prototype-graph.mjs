import { LOGGED_OUT_BOOT } from './bootEntries.mjs'

// The entry renders nothing until these dynamic imports load, so check-eager-graph.mjs counts them all.
export const AUTH_PROTOTYPE_BOOT = [
    'src/auth-prototype/authPrototypeEntry.tsx',
    'src/auth-prototype/AuthPrototype.tsx',
    'src/initKea.ts',
    'src/loadPostHogJS.tsx',
]
export const AUTH_PROTOTYPE_META = 'auth-prototype-esbuild-meta.json'

function rootBytes(eagerGraphReport, rootModules, label) {
    const name = rootModules.join(' + ')
    const root = eagerGraphReport.roots?.find((item) => item.root === name)
    if (!root) {
        throw new Error(`No ${label} root '${name}' in the eager graph report`)
    }
    return root
}

export function authPrototypeBootShare(eagerGraphReport) {
    const authPrototype = rootBytes(eagerGraphReport, AUTH_PROTOTYPE_BOOT, 'auth prototype')
    const current = rootBytes(eagerGraphReport, LOGGED_OUT_BOOT, 'logged-out boot')
    return {
        bytes: authPrototype.bytes,
        files: authPrototype.files,
        currentBytes: current.bytes,
        share: authPrototype.bytes / current.bytes,
    }
}
