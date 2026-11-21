import { closeSync, openSync, renameSync, rmSync, writeFileSync, writeSync } from 'fs'
import path from 'path'

// A full ladder's journal or truth can outgrow the longest string the engine holds, so an array is written one
// element at a time, in the same bytes JSON.stringify(value, null, 2) gives.
function writeArray(file: string, items: unknown[]): void {
    const fd = openSync(file, 'w')
    try {
        writeSync(fd, '[')
        items.forEach((item, index) => {
            const element = (JSON.stringify(item, null, 2) ?? 'null').replaceAll('\n', '\n  ')
            writeSync(fd, `${index === 0 ? '' : ','}\n  ${element}`)
        })
        writeSync(fd, items.length === 0 ? ']' : '\n]')
    } finally {
        closeSync(fd)
    }
}

export function writeJson(evidenceDir: string, name: string, value: unknown): void {
    const file = path.join(evidenceDir, name)
    const partial = `${file}.partial`
    try {
        if (Array.isArray(value)) {
            writeArray(partial, value)
        } else {
            writeFileSync(partial, JSON.stringify(value, null, 2))
        }
        renameSync(partial, file)
    } catch (error) {
        rmSync(partial, { force: true })
        throw error
    }
}
