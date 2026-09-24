import fs from 'node:fs'
import path from 'node:path'

// The App and Exporter builds share dist/, so one build must never delete a stylesheet the other links.
// Keyed by entry, so only each entry's current stylesheet is protected.
const linkedStylesheets = new Map()

/**
 * With code splitting, esbuild writes a stylesheet for every chunk that imports CSS, and each one
 * holds all the CSS reachable from that chunk. The page links only the entry's stylesheet, which
 * already contains all of it, so the other stylesheets are never downloaded. Deletes them and
 * their source maps so they do not ship in the image.
 *
 * `outputs` is the esbuild metafile's `outputs`, and `entryPoint` the entry whose stylesheet the
 * page links. Throws, without deleting anything, when that entry has no stylesheet.
 */
export function removeUnlinkedStylesheets(absWorkingDir, outputs, entryPoint) {
    const entry = Object.entries(outputs).find(
        ([file, output]) => output.entryPoint === entryPoint && file.endsWith('.js')
    )
    const linked = entry?.[1].cssBundle
    if (!linked) {
        throw new Error(`No linked stylesheet found for ${entryPoint}, so no stylesheet was removed.`)
    }
    linkedStylesheets.set(`${absWorkingDir}:${entryPoint}`, path.resolve(absWorkingDir, linked))
    const protectedFiles = new Set(linkedStylesheets.values())

    let removedBytes = 0
    for (const [file, output] of Object.entries(outputs)) {
        const absolute = path.resolve(absWorkingDir, file)
        if (!file.endsWith('.css') || protectedFiles.has(absolute)) {
            continue
        }
        fs.rmSync(absolute, { force: true })
        fs.rmSync(path.resolve(absWorkingDir, `${file}.map`), { force: true })
        removedBytes += output.bytes
    }
    return removedBytes
}
