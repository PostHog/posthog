import fs from 'node:fs'
import path from 'node:path'

const linkedStylesheets = new Map()
const buildOutputs = new Map()

export function resetModuleState() {
    linkedStylesheets.clear()
    buildOutputs.clear()
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
    linkedStylesheets.set(buildKey, path.resolve(absWorkingDir, linked))
    buildOutputs.set(buildKey, outputs)
    if (linkedStylesheets.size < 2) {
        return 0
    }

    const protectedFiles = new Set(linkedStylesheets.values())
    let removedBytes = 0
    for (const build of buildOutputs.values()) {
        for (const [file, output] of Object.entries(build)) {
            const absolute = path.resolve(absWorkingDir, file)
            if (!file.endsWith('.css') || protectedFiles.has(absolute)) {
                continue
            }
            fs.rmSync(absolute, { force: true })
            fs.rmSync(path.resolve(absWorkingDir, `${file}.map`), { force: true })
            removedBytes += output.bytes
        }
    }
    return removedBytes
}
