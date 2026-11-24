import { basename } from 'node:path'
import { gunzipSync, inflateRawSync } from 'node:zlib'

import { HogError } from '@/core/errors'

// Reads only the parts of tar and zip that release/package.ts writes, so it needs no dependency.

// Far above any hog binary, so a small archive that unpacks to gigabytes fails instead of filling memory.
export const MAX_EXTRACTED_BYTES = 1024 * 1024 * 1024

export function brokenArchive(reason: string): HogError {
    return new HogError(
        'invalid_release_archive',
        `The downloaded archive is broken: ${reason}.`,
        'Run `hog upgrade` again.'
    )
}

const tooLarge = (maxBytes: number): HogError => brokenArchive(`it unpacks to more than ${maxBytes} bytes`)

function text(bytes: Uint8Array): string {
    const end = bytes.indexOf(0)
    return new TextDecoder().decode(end === -1 ? bytes : bytes.subarray(0, end))
}

// macOS tar stores a file's extended attributes as a second entry named `._<file>`.
const isShipped = (entry: string): boolean => !basename(entry).startsWith('.')

function fromTarGz(archive: Uint8Array, maxBytes: number): Map<string, Uint8Array> {
    const files = new Map<string, Uint8Array>()
    const tar = gunzipSync(archive, { maxOutputLength: maxBytes })
    let offset = 0
    while (offset + 512 <= tar.length) {
        const header = tar.subarray(offset, offset + 512)
        if (header.every((byte) => byte === 0)) {
            break
        }
        const entry = text(header.subarray(0, 100))
        const size = Number.parseInt(text(header.subarray(124, 136)).trim() || '0', 8)
        const type = String.fromCharCode(header[156] ?? 0)
        const start = offset + 512
        if ((type === '0' || type === '\0') && isShipped(entry)) {
            files.set(basename(entry), tar.subarray(start, start + size))
        }
        offset = start + Math.ceil(size / 512) * 512
    }
    return files
}

function fromZip(archive: Uint8Array, maxBytes: number): Map<string, Uint8Array> {
    const files = new Map<string, Uint8Array>()
    const view = new DataView(archive.buffer, archive.byteOffset, archive.byteLength)
    let end = archive.length - 22
    while (end >= 0 && view.getUint32(end, true) !== 0x06054b50) {
        end--
    }
    if (end < 0) {
        throw brokenArchive('it is not a zip file')
    }

    let entry = view.getUint32(end + 16, true)
    const count = view.getUint16(end + 10, true)
    let extracted = 0
    for (let index = 0; index < count; index++) {
        if (view.getUint32(entry, true) !== 0x02014b50) {
            throw brokenArchive('its file list is damaged')
        }
        const method = view.getUint16(entry + 10, true)
        const compressedSize = view.getUint32(entry + 20, true)
        const nameLength = view.getUint16(entry + 28, true)
        const extraLength = view.getUint16(entry + 30, true)
        const commentLength = view.getUint16(entry + 32, true)
        const localHeader = view.getUint32(entry + 42, true)
        const entryName = new TextDecoder().decode(archive.subarray(entry + 46, entry + 46 + nameLength))

        if (!entryName.endsWith('/') && isShipped(entryName)) {
            const dataStart =
                localHeader + 30 + view.getUint16(localHeader + 26, true) + view.getUint16(localHeader + 28, true)
            const data = archive.subarray(dataStart, dataStart + compressedSize)
            if (method !== 0 && method !== 8) {
                throw brokenArchive(`it uses compression method ${method}`)
            }
            // The limit covers every entry together, so many small entries can't add up past it.
            const remaining = maxBytes - extracted
            const contents =
                method === 0 || data.length === 0
                    ? data
                    : inflateRawSync(data, { maxOutputLength: Math.max(remaining, 1) })
            extracted += contents.length
            if (extracted > maxBytes) {
                throw tooLarge(maxBytes)
            }
            files.set(basename(entryName), contents)
        }
        entry += 46 + nameLength + extraLength + commentLength
    }
    return files
}

export function extractAll(
    archive: Uint8Array,
    archiveName: string,
    maxBytes: number = MAX_EXTRACTED_BYTES
): Map<string, Uint8Array> {
    try {
        return archiveName.endsWith('.zip') ? fromZip(archive, maxBytes) : fromTarGz(archive, maxBytes)
    } catch (error) {
        if ((error as NodeJS.ErrnoException).code === 'ERR_BUFFER_TOO_LARGE') {
            throw tooLarge(maxBytes)
        }
        throw error instanceof HogError ? error : brokenArchive(error instanceof Error ? error.message : String(error))
    }
}
