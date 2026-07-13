import fs from 'fs'
import path from 'path'

// Shared helpers for the toolbar build checks (check-toolbar-size.mjs,
// check-toolbar-csp-eval.mjs). The toolbar app build writes its metafile to
// toolbar-esbuild-meta.json (config name 'Toolbar'); the loader (dist/toolbar.js)
// is built separately and is not part of the metafile.

export const TOOLBAR_ENTRY_POINT = 'src/toolbar/index.tsx'

export function readToolbarMetafile() {
    const metafilePath = path.resolve(process.cwd(), 'toolbar-esbuild-meta.json')
    try {
        return JSON.parse(fs.readFileSync(metafilePath, 'utf-8'))
    } catch {
        console.error('✗ Could not read toolbar-esbuild-meta.json — build the toolbar before running this check.')
        process.exit(1)
    }
}

export function findEntryOutput(outputs) {
    const entry = Object.keys(outputs).find((o) => outputs[o].entryPoint === TOOLBAR_ENTRY_POINT)
    if (!entry) {
        console.error(`✗ No output with entryPoint ${TOOLBAR_ENTRY_POINT} in the toolbar metafile.`)
        process.exit(1)
    }
    return entry
}

/**
 * The eager set: the entry output plus everything reachable from it through static
 * `import` statements — i.e. the files fetched before the toolbar can run at all.
 * Dynamic-import edges are the split points; their targets load on demand.
 */
export function eagerOutputs(outputs) {
    const entry = findEntryOutput(outputs)
    const eager = new Set()
    const walk = (output) => {
        if (eager.has(output)) {
            return
        }
        eager.add(output)
        for (const imp of outputs[output].imports || []) {
            if (!imp.external && imp.kind === 'import-statement') {
                walk(imp.path)
            }
        }
    }
    walk(entry)
    return eager
}

export function jsOutputs(outputs) {
    return Object.keys(outputs).filter((o) => o.endsWith('.js'))
}
