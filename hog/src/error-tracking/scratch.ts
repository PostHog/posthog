import { closeSync, mkdtempSync, openSync, readSync, rmSync, writeSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import type { StoredData } from './upload'

// One temporary file that holds what a command reads back later, such as the containers of a
// JavaScript build between the step that builds them and the step that uploads them. Memory use
// then follows the largest bundle, not the whole build.
export class Scratch {
    private file: { descriptor: number; folder: string | undefined } | undefined
    private size = 0

    write = (bytes: Uint8Array): StoredData => {
        const descriptor = this.open()
        const start = this.size
        // writeSync can write fewer bytes than asked, so it runs until every byte is written.
        for (let written = 0; written < bytes.length; ) {
            written += writeSync(descriptor, bytes, written, bytes.length - written, start + written)
        }
        this.size += bytes.length

        const length = bytes.length
        return {
            length,
            read: () => {
                const out = Buffer.allocUnsafe(length)
                for (let read = 0; read < length; ) {
                    const count = readSync(descriptor, out, read, length - read, start + read)
                    if (count === 0) {
                        throw new Error('The temporary upload file is shorter than what hog wrote to it.')
                    }
                    read += count
                }
                return out
            },
        }
    }

    private open(): number {
        if (this.file) {
            return this.file.descriptor
        }
        const folder = mkdtempSync(join(tmpdir(), 'hog-'))
        const descriptor = openSync(join(folder, 'scratch'), 'wx+', 0o600)
        this.file = { descriptor, folder }

        // The open descriptor keeps an unlinked file readable, and the system frees it when hog
        // exits, even when hog is killed.
        try {
            rmSync(folder, { recursive: true })
            this.file.folder = undefined
        } catch {
            // Windows can't remove an open file, so there the folder stays until `dispose`.
        }
        return descriptor
    }

    dispose(): void {
        if (!this.file) {
            return
        }
        closeSync(this.file.descriptor)
        if (this.file.folder !== undefined) {
            rmSync(this.file.folder, { recursive: true, force: true })
        }
        this.file = undefined
    }
}

export const sizeOnly = (bytes: Uint8Array): StoredData => ({
    length: bytes.length,
    read: () => {
        throw new Error('A dry run keeps no upload data.')
    },
})
