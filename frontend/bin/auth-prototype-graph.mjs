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
    for (const file of chunks) {
        const css = outputs[file].cssBundle
        if (css) {
            if (!outputs[css]) {
                throw new Error(`No auth prototype CSS output for ${file}: ${css}`)
            }
            files.add(css)
        }
    }
    return { bytes: [...files].reduce((total, file) => total + outputs[file].bytes, 0), files: files.size }
}
