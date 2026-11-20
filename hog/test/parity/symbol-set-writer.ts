import { constants, deflateRawSync, zstdCompressSync } from 'node:zlib'

import type { SymbolDataType } from '@/error-tracking/container'

// Symbol sets for tests that only read them: the extract and download scenarios, and the cases
// that damage a container on purpose. hog-worker builds the symbol sets that upload, and nothing
// holds these zips to posthog-cli's bytes.

const MAGIC = Buffer.from('posthog_error_tracking', 'latin1')
const VERSION = 2
const COMPRESSION_ZSTD = 1
const ZSTD_LEVEL = 3

const LOCAL_HEADER = 0x04034b50
const CENTRAL_HEADER = 0x02014b50
const END_OF_CENTRAL_DIRECTORY = 0x06054b50
const LOCAL_HEADER_LENGTH = 30
const CENTRAL_HEADER_LENGTH = 46
const END_LENGTH = 22
const VERSION_NEEDED = 20
const DEFLATED = 8
const UTF8_NAME = 0x0800

export function writeSymbolData(type: SymbolDataType, payload: Uint8Array): Buffer {
    const header = Buffer.alloc(MAGIC.length + 9)
    MAGIC.copy(header)
    header.writeUInt32LE(VERSION, MAGIC.length)
    header.writeUInt32LE(type, MAGIC.length + 4)
    header.writeUInt8(COMPRESSION_ZSTD, MAGIC.length + 8)

    // The pledged size puts the content size in the frame header, as posthog-symbol-data does, so a
    // small container hashes like the one hog-worker writes.
    const compressed = zstdCompressSync(payload, {
        pledgedSrcSize: payload.length,
        params: { [constants.ZSTD_c_compressionLevel]: ZSTD_LEVEL },
    } as Parameters<typeof zstdCompressSync>[1])
    return Buffer.concat([header, compressed])
}

export function writeZip(entries: Record<string, Uint8Array | string>): Buffer {
    const locals: Buffer[] = []
    const central: Buffer[] = []
    let offset = 0
    for (const [entryName, contents] of Object.entries(entries)) {
        const name = Buffer.from(entryName, 'utf8')
        const data = Buffer.from(contents)
        const compressed = deflateRawSync(data)

        const local = Buffer.alloc(LOCAL_HEADER_LENGTH)
        local.writeUInt32LE(LOCAL_HEADER, 0)
        local.writeUInt16LE(VERSION_NEEDED, 4)
        local.writeUInt16LE(UTF8_NAME, 6)
        local.writeUInt16LE(DEFLATED, 8)
        local.writeUInt32LE(Bun.hash.crc32(data), 14)
        local.writeUInt32LE(compressed.length, 18)
        local.writeUInt32LE(data.length, 22)
        local.writeUInt16LE(name.length, 26)

        const header = Buffer.alloc(CENTRAL_HEADER_LENGTH)
        header.writeUInt32LE(CENTRAL_HEADER, 0)
        header.writeUInt16LE(VERSION_NEEDED, 4)
        header.writeUInt16LE(VERSION_NEEDED, 6)
        local.copy(header, 8, 6, LOCAL_HEADER_LENGTH)
        header.writeUInt32LE(offset, 42)

        locals.push(local, name, compressed)
        central.push(header, name)
        offset += local.length + name.length + compressed.length
    }

    const directory = Buffer.concat(central)
    const end = Buffer.alloc(END_LENGTH)
    end.writeUInt32LE(END_OF_CENTRAL_DIRECTORY, 0)
    end.writeUInt16LE(central.length / 2, 8)
    end.writeUInt16LE(central.length / 2, 10)
    end.writeUInt32LE(directory.length, 12)
    end.writeUInt32LE(offset, 16)
    return Buffer.concat([...locals, directory, end])
}
