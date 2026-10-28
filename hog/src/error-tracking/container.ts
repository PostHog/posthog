import { createHash } from 'node:crypto'
import { constants, zstdCompressSync, zstdDecompressSync } from 'node:zlib'

import { HogError } from '@/core/errors'

// The symbol-data container from the posthog-symbol-data crate (0.5.2). Its bytes are what PostHog
// stores and what most content hashes cover, so every byte must match what posthog-cli writes.
export enum SymbolDataType {
    SourceAndMap = 2,
    HermesMap = 3,
    ProguardMapping = 4,
    AppleDsym = 5,
    ElfDebugInfo = 6,
}

const MAGIC = Buffer.from('posthog_error_tracking', 'latin1')
const VERSION = 2
const HEADER_LENGTH = MAGIC.length + 4 + 4 + 1
const COMPRESSION_ZSTD = 1
const ZSTD_BLOCK_SIZE = 128 * 1024

// Matches the Rust `zstd::Encoder` at level 3 with the source size pledged: one `compressStream` call
// over the whole input, then `endStream`. That differs from one-shot compression in one case: when
// the input is an exact multiple of the 128 KiB block size and larger than one block, the encoder
// marks the final data block as not last and appends an empty last block (`01 00 00`).
// `node:zlib` runs through libzstd's streaming API, which matches above the 2 MiB window, where
// `Bun.zstdCompressSync` does not.
export function zstdCompressLikeRust(raw: Uint8Array): Buffer {
    const compressed = zstdCompressSync(raw, {
        pledgedSrcSize: raw.length,
        params: { [constants.ZSTD_c_compressionLevel]: 3 },
    } as Parameters<typeof zstdCompressSync>[1])
    if (raw.length <= ZSTD_BLOCK_SIZE || raw.length % ZSTD_BLOCK_SIZE !== 0) {
        return compressed
    }
    return appendEmptyLastBlock(compressed)
}

// Walks the frame header (RFC 8878, section 3.1.1.1) and the blocks to the last one, clears its
// last-block bit, and appends an empty raw block flagged as last.
function appendEmptyLastBlock(frame: Buffer): Buffer {
    const descriptor = frame[4]!
    const contentSizeFlag = descriptor >> 6
    const singleSegment = (descriptor >> 5) & 1
    const dictionaryFlag = descriptor & 3
    let offset =
        5 + (singleSegment ? 0 : 1) + [0, 1, 2, 4][dictionaryFlag]! + [singleSegment ? 1 : 0, 2, 4, 8][contentSizeFlag]!
    for (;;) {
        const header = frame[offset]! | (frame[offset + 1]! << 8) | (frame[offset + 2]! << 16)
        const isLast = header & 1
        const blockType = (header >> 1) & 3
        const blockSize = header >>> 3
        if (isLast) {
            const out = Buffer.alloc(frame.length + 3)
            frame.copy(out)
            out[offset] = out[offset]! & 0xfe
            out.set([1, 0, 0], frame.length)
            return out
        }
        // An RLE block stores one byte, whatever size it expands to.
        offset += 3 + (blockType === 1 ? 1 : blockSize)
    }
}

export function writeSymbolData(type: SymbolDataType, raw: Uint8Array): Buffer {
    const header = Buffer.alloc(HEADER_LENGTH)
    MAGIC.copy(header)
    header.writeUInt32LE(VERSION, MAGIC.length)
    header.writeUInt32LE(type, MAGIC.length + 4)
    header.writeUInt8(COMPRESSION_ZSTD, MAGIC.length + 8)
    return Buffer.concat([header, zstdCompressLikeRust(raw)])
}

export function readSymbolData(bytes: Uint8Array): { type: number; payload: Buffer } {
    const data = Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength)
    if (data.length < MAGIC.length + 4 || !data.subarray(0, MAGIC.length).equals(MAGIC)) {
        throw new HogError('invalid_symbol_set', "The file isn't a PostHog symbol set: the header doesn't match.")
    }
    const version = data.readUInt32LE(MAGIC.length)
    const type = data.readUInt32LE(MAGIC.length + 4)
    // Version 1 has no compression byte and is never compressed.
    if (version === 1) {
        return { type, payload: data.subarray(MAGIC.length + 8) }
    }
    if (version !== VERSION) {
        throw new HogError('invalid_symbol_set', `Unsupported symbol set version ${version}, expected 1 or 2.`)
    }
    const body = data.subarray(HEADER_LENGTH)
    return { type, payload: data[MAGIC.length + 8] === COMPRESSION_ZSTD ? zstdDecompressSync(body) : body }
}

// SHA-512 over the parts joined with nothing in between, as lowercase hex. Most uploads hash their
// whole container this way.
export function contentHash(...parts: (Uint8Array | string)[]): string {
    const hash = createHash('sha512')
    for (const part of parts) {
        hash.update(part)
    }
    return hash.digest('hex')
}

export function sourceAndMapPayload(source: Uint8Array, map: Uint8Array): Buffer {
    const sourceLength = Buffer.alloc(8)
    sourceLength.writeBigUInt64LE(BigInt(source.length))
    const mapLength = Buffer.alloc(8)
    mapLength.writeBigUInt64LE(BigInt(map.length))
    return Buffer.concat([sourceLength, source, mapLength, map])
}
