import fs from 'node:fs'
import path from 'node:path'

const buildState = new Map()
let cleanupDone = false

export function resetModuleState() {
    buildState.clear()
    cleanupDone = false
}

export function removeUnlinkedStylesheets(absWorkingDir, outputs, entryPoint) {
    const entry = Object.entries(outputs).find(
        ([file, output]) => output.entryPoint === entryPoint && file.endsWith('.js')
    )
    const linked = entry?.[1].cssBundle
    if (!linked) {
        throw new Error(`No linked stylesheet found for ${entryPoint}, so no stylesheet was removed.`)
    }

    const buildKey = `${absWorkingDir}:${entryPoint}`
    const linkedPath = path.resolve(absWorkingDir, linked)
    buildState.set(buildKey, { outputs, linkedPath })

    if (buildState.size < 2 || cleanupDone) {
        return 0
    }

    const protectedFiles = new Set(buildState.values().map((state) => state.linkedPath))
    let removedBytes = 0
    for (const { outputs: build } of buildState.values()) {
        for (const [file, output] of Object.entries(build)) {
            if (!file.endsWith('.css')) {
                continue
            }
            const absolute = path.resolve(absWorkingDir, file)
            if (protectedFiles.has(absolute)) {
                continue
            }
            fs.rmSync(absolute, { force: true })
            fs.rmSync(path.resolve(absWorkingDir, `${file}.map`), { force: true })
            removedBytes += output.bytes
        }
    }
    cleanupDone = true
    return removedBytes
}
