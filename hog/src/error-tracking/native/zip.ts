import { deflateRaw } from 'pako'

// The zip posthog-cli builds with the `zip` crate 2.4.2: deflate at level 6 through stock zlib,
// the fixed 1980-01-01 timestamp, Unix 0644 attributes, no extra fields, no data descriptor.
// pako reproduces stock zlib's output. Bun's own deflate does not, and the zip is hashed.

const LOCAL_HEADER = 0x04034b50
const CENTRAL_HEADER = 0x02014b50
const END_OF_CENTRAL_DIRECTORY = 0x06054b50
const ZIP64_END_OF_CENTRAL_DIRECTORY = 0x06064b50
const ZIP64_END_LOCATOR = 0x07064b50
const MAX_ENTRIES = 0xffff
const VERSION_NEEDED = 20
const VERSION_MADE_BY = 0x0314
const DEFLATED = 8
const DOS_DATE = 0x0021
const UNIX_FILE_0644 = 0x81a40000
const UTF8_NAME = 0x0800

const CRC_TABLE = (() => {
    const table = new Uint32Array(256)
    for (let index = 0; index < 256; index++) {
        let value = index
        for (let bit = 0; bit < 8; bit++) {
            value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1
        }
        table[index] = value >>> 0
    }
    return table
})()

export function crc32(bytes: Uint8Array): number {
    let crc = 0xffffffff
    for (const byte of bytes) {
        crc = CRC_TABLE[(crc ^ byte) & 0xff]! ^ (crc >>> 8)
    }
    return (crc ^ 0xffffffff) >>> 0
}

export class ZipError extends Error {}

interface Entry {
    name: Buffer
    flags: number
    crc: number
    compressedSize: number
    size: number
    offset: number
}

export class ZipWriter {
    private readonly chunks: Uint8Array[] = []
    private readonly entries: Entry[] = []
    private length = 0
    private readonly names = new Set<string>()

    add(name: string, data: Uint8Array): void {
        if (this.names.has(name)) {
            throw new ZipError('Duplicate filename')
        }
        if (data.length > 0xffffffff) {
            throw new ZipError('Large file option has not been set')
        }
        this.names.add(name)
        const encoded = Buffer.from(name, 'utf8')
        const compressed = deflateRaw(data, { level: 6, windowBits: 15, memLevel: 8, strategy: 0 })
        const entry: Entry = {
            name: encoded,
            flags: encoded.every((byte) => byte < 0x80) ? 0 : UTF8_NAME,
            crc: crc32(data),
            compressedSize: compressed.length,
            size: data.length,
            offset: this.length,
        }
        const header = Buffer.alloc(30)
        header.writeUInt32LE(LOCAL_HEADER, 0)
        header.writeUInt16LE(VERSION_NEEDED, 4)
        header.writeUInt16LE(entry.flags, 6)
        header.writeUInt16LE(DEFLATED, 8)
        header.writeUInt16LE(0, 10)
        header.writeUInt16LE(DOS_DATE, 12)
        header.writeUInt32LE(entry.crc, 14)
        header.writeUInt32LE(entry.compressedSize, 18)
        header.writeUInt32LE(entry.size, 22)
        header.writeUInt16LE(encoded.length, 26)
        header.writeUInt16LE(0, 28)
        this.push(header, encoded, compressed)
        this.entries.push(entry)
    }

    finish(): Buffer {
        // More than 65,535 entries is the only ZIP64 case hog writes. Offsets past 4 GiB would also
        // need ZIP64 fields in each entry.
        if (this.length > 0xffffffff) {
            throw new ZipError('Zip64 archives over 4 GiB are not supported')
        }
        const directoryOffset = this.length
        for (const entry of this.entries) {
            const header = Buffer.alloc(46)
            header.writeUInt32LE(CENTRAL_HEADER, 0)
            header.writeUInt16LE(VERSION_MADE_BY, 4)
            header.writeUInt16LE(VERSION_NEEDED, 6)
            header.writeUInt16LE(entry.flags, 8)
            header.writeUInt16LE(DEFLATED, 10)
            header.writeUInt16LE(0, 12)
            header.writeUInt16LE(DOS_DATE, 14)
            header.writeUInt32LE(entry.crc, 16)
            header.writeUInt32LE(entry.compressedSize, 20)
            header.writeUInt32LE(entry.size, 24)
            header.writeUInt16LE(entry.name.length, 28)
            header.writeUInt32LE(UNIX_FILE_0644, 38)
            header.writeUInt32LE(entry.offset, 42)
            this.push(header, entry.name)
        }
        const directorySize = this.length - directoryOffset
        if (this.entries.length > MAX_ENTRIES) {
            const record = Buffer.alloc(56)
            record.writeUInt32LE(ZIP64_END_OF_CENTRAL_DIRECTORY, 0)
            record.writeBigUInt64LE(44n, 4)
            record.writeUInt16LE(VERSION_NEEDED, 12)
            record.writeUInt16LE(VERSION_NEEDED, 14)
            record.writeBigUInt64LE(BigInt(this.entries.length), 24)
            record.writeBigUInt64LE(BigInt(this.entries.length), 32)
            record.writeBigUInt64LE(BigInt(directorySize), 40)
            record.writeBigUInt64LE(BigInt(directoryOffset), 48)
            const locator = Buffer.alloc(20)
            locator.writeUInt32LE(ZIP64_END_LOCATOR, 0)
            locator.writeBigUInt64LE(BigInt(directoryOffset + directorySize), 8)
            locator.writeUInt32LE(1, 16)
            this.push(record, locator)
        }
        const count = Math.min(this.entries.length, MAX_ENTRIES)
        const end = Buffer.alloc(22)
        end.writeUInt32LE(END_OF_CENTRAL_DIRECTORY, 0)
        end.writeUInt16LE(count, 8)
        end.writeUInt16LE(count, 10)
        end.writeUInt32LE(directorySize, 12)
        end.writeUInt32LE(directoryOffset, 16)
        this.push(end)
        return Buffer.concat(this.chunks)
    }

    private push(...parts: Uint8Array[]): void {
        for (const part of parts) {
            this.chunks.push(part)
            this.length += part.length
        }
    }
}
