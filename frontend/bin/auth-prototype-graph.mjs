import { LOGGED_OUT_BOOT } from './bootEntries.mjs'

const ENTRY = 'src/auth-prototype/authPrototypeEntry.tsx'
const REQUIRED_IMPORTS = ['src/auth-prototype/AuthPrototype.tsx', 'src/initKea.ts', 'src/loadPostHogJS.tsx']

export function authPrototypeBootBytes({ inputs, outputs }) {
    const dynamicImports = new Set(
        inputs?.[ENTRY]?.imports?.filter((item) => item.kind === 'dynamic-import').map((item) => item.path) ?? []
    )
    for (const module of REQUIRED_IMPORTS) {
        if (!dynamicImports.has(module)) {
            throw new Error(`Auth prototype entry must dynamically import ${module}`)
        }
    }

    const roots = [ENTRY, ...REQUIRED_IMPORTS]
    const chunks = new Set()
    const queue = roots.map((root) => {
        const output = Object.keys(outputs ?? {}).find(
            (file) => outputs[file].entryPoint === root && file.endsWith('.js')
        )
        if (!output) {
            throw new Error(`No auth prototype output chunk for ${root}`)
        }
        return output
    })
    const entryStylesheet = outputs[queue[0]].cssBundle
    for (const file of queue) {
        chunks.add(file)
    }
    while (queue.length) {
        const file = queue.shift()
        for (const imported of outputs[file].imports ?? []) {
            if (imported.kind === 'import-statement' && outputs[imported.path] && !chunks.has(imported.path)) {
                chunks.add(imported.path)
                queue.push(imported.path)
            }
        }
    }

    const files = new Set(chunks)
    if (entryStylesheet) {
        if (!outputs[entryStylesheet]) {
            throw new Error(`No auth prototype CSS output: ${entryStylesheet}`)
        }
        files.add(entryStylesheet)
    }
    return { bytes: [...files].reduce((total, file) => total + outputs[file].bytes, 0), files: files.size }
}

const LOGGED_OUT_BOOT_ROOT = LOGGED_OUT_BOOT.join(' + ')

export function currentLoginBootBytes(eagerGraphReport) {
    const root = eagerGraphReport.roots?.find((item) => item.root === LOGGED_OUT_BOOT_ROOT)
    if (!root) {
        throw new Error(`No logged-out boot root '${LOGGED_OUT_BOOT_ROOT}' in the eager graph report`)
    }
    return root.bytes
}
