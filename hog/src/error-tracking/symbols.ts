import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, isAbsolute, join, relative, resolve } from 'node:path'
import { inflateRawSync, zstdDecompressSync } from 'node:zlib'

import { HogError } from '@/core/errors'
import type { RuntimeFetch } from '@/core/runtime'

import { SymbolDataType } from './container'
import { decodeUtf8 } from './json'
import { crc32 } from './native/zip'
import { ApiFailure, type SymbolSetClient } from './upload'

const MAGIC = Buffer.from('posthog_error_tracking', 'latin1')
// Uploads are at most 100 MB compressed. These caps stop a crafted symbol set from inflating
// until the process runs out of memory.
const MAX_PAYLOAD_BYTES = 2 * 1024 * 1024 * 1024
const MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
const DOWNLOAD_TIMEOUT_MS = 10 * 60 * 1000

export type ExtractedKind = 'sourcemap' | 'hermes' | 'proguard' | 'elf' | 'dsym'

export interface ExtractReport {
    kind: ExtractedKind
    output: string
    files: string[]
}

// Rust's `Path` splits on `\` too on Windows.
const pathParts = (path: string, platform: NodeJS.Platform): string[] =>
    path.split(platform === 'win32' ? /[\\/]/ : '/')

// `derive_base_name`: the last path component, without the extension the extracted files get back.
// posthog-cli checks for `.` and `..` before it strips the extension, so `...dSYM` becomes `..`
// there. hog checks after too, so the files never land above the output folder.
export function deriveBaseName(reference: string, platform: NodeJS.Platform = process.platform): string {
    const parts = pathParts(reference, platform).filter((part) => part !== '' && part !== '.')
    let name = parts.length === 0 ? reference : parts[parts.length - 1]!
    if (name === '..' || name === '.') {
        name = 'symbol_set'
    }
    for (const suffix of ['.js.map', '.hbc.map', '.map', '.js', '.txt', '.dSYM']) {
        if (name.endsWith(suffix)) {
            name = name.slice(0, -suffix.length)
            break
        }
    }
    return name === '' || name === '.' || name === '..' ? 'symbol_set' : name
}

class SymbolDataError extends Error {
    constructor(
        message: string,
        readonly wrongType?: number
    ) {
        super(message)
    }
}

// posthog-symbol-data's `read_symbol_data` for one expected type: the header, then the type, then
// the payload, which decides whether this type fits.
function readPayload(data: Buffer, expected: SymbolDataType): Buffer {
    if (data.length < MAGIC.length + 4) {
        throw new SymbolDataError(`Data too short, expected ${MAGIC.length + 4}, got ${data.length}`)
    }
    if (!data.subarray(0, MAGIC.length).equals(MAGIC)) {
        throw new SymbolDataError('Invalid magic')
    }
    const version = data.readUInt32LE(MAGIC.length)
    if (version !== 1 && version !== 2) {
        throw new SymbolDataError(`Wrong version: ${version}, expected 2`)
    }
    const headerLength = MAGIC.length + (version === 1 ? 8 : 9)
    if (data.length < headerLength) {
        throw new SymbolDataError(`Data too short, expected ${headerLength}, got ${data.length}`)
    }
    const type = data.readUInt32LE(MAGIC.length + 4)
    if (type !== expected) {
        throw new SymbolDataError(`Invalid data type ${type}`, type)
    }
    const body = data.subarray(headerLength)
    if (version === 1) {
        return body
    }
    const compression = data[headerLength - 1]
    if (compression === 0) {
        return body
    }
    if (compression !== 1) {
        throw new SymbolDataError(`Unknown compression ${compression}`)
    }
    try {
        return zstdDecompressSync(body, { maxOutputLength: MAX_PAYLOAD_BYTES })
    } catch (error) {
        throw new SymbolDataError(`The payload doesn't decompress: ${(error as Error).message}`)
    }
}

function sourceAndMap(payload: Buffer): { source: Buffer; map: Buffer } {
    const read = (at: number): { bytes: Buffer; end: number } => {
        if (at + 8 > payload.length) {
            throw new SymbolDataError('Truncated payload')
        }
        const length = payload.readBigUInt64LE(at)
        const end = BigInt(at + 8) + length
        if (end > BigInt(payload.length)) {
            throw new SymbolDataError('Truncated payload')
        }
        return { bytes: payload.subarray(at + 8, Number(end)), end: Number(end) }
    }
    const source = read(0)
    const map = read(source.end)
    if (map.end !== payload.length) {
        throw new SymbolDataError('Trailing bytes in payload')
    }
    decodeUtf8(source.bytes)
    decodeUtf8(map.bytes)
    return { source: source.bytes, map: map.bytes }
}

interface ZipEntry {
    name: string
    data: Buffer
}

function readZip(zip: Buffer): ZipEntry[] {
    const unreadable = (why: string): HogError =>
        new HogError('invalid_symbol_set', `The symbol set's zip archive is unreadable: ${why}.`)
    const end = zip.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]))
    if (end < 0 || end + 22 > zip.length) {
        throw unreadable('no end of central directory')
    }
    let count = zip.readUInt16LE(end + 10)
    let offset = zip.readUInt32LE(end + 16)
    // An archive with more than 65,535 entries keeps the real count in the ZIP64 record, which the
    // locator just before the end record points at.
    const locator = end - 20
    if (locator >= 0 && zip.readUInt32LE(locator) === 0x07064b50) {
        const record = Number(zip.readBigUInt64LE(locator + 8))
        if (record + 56 > zip.length || zip.readUInt32LE(record) !== 0x06064b50) {
            throw unreadable('the ZIP64 end of central directory is out of bounds')
        }
        count = Number(zip.readBigUInt64LE(record + 32))
        offset = Number(zip.readBigUInt64LE(record + 48))
    }
    let total = 0
    const entries: ZipEntry[] = []
    for (let index = 0; index < count; index++) {
        if (offset + 46 > zip.length || zip.readUInt32LE(offset) !== 0x02014b50) {
            throw unreadable('a central directory entry is out of bounds')
        }
        const method = zip.readUInt16LE(offset + 10)
        const crc = zip.readUInt32LE(offset + 16)
        const compressedSize = zip.readUInt32LE(offset + 20)
        const size = zip.readUInt32LE(offset + 24)
        const nameLength = zip.readUInt16LE(offset + 28)
        const extraLength = zip.readUInt16LE(offset + 30)
        const commentLength = zip.readUInt16LE(offset + 32)
        const local = zip.readUInt32LE(offset + 42)
        const name = zip.subarray(offset + 46, offset + 46 + nameLength).toString('utf8')
        if (local + 30 > zip.length) {
            throw unreadable(`${name} is out of bounds`)
        }
        const dataStart = local + 30 + zip.readUInt16LE(local + 26) + zip.readUInt16LE(local + 28)
        if (dataStart + compressedSize > zip.length) {
            throw unreadable(`${name} is out of bounds`)
        }
        if (method !== 0 && method !== 8) {
            throw new HogError(
                'invalid_symbol_set',
                `The symbol set's zip uses compression method ${method}, which hog can't read.`
            )
        }
        total += size
        if (total > MAX_ARCHIVE_BYTES) {
            throw unreadable('it unpacks to more than 2 GiB')
        }
        const raw = zip.subarray(dataStart, dataStart + compressedSize)
        let data: Buffer
        try {
            data = method === 8 ? inflateRawSync(raw, { maxOutputLength: Math.max(1, size) }) : raw
        } catch (error) {
            throw unreadable(`${name} doesn't decompress: ${(error as Error).message}`)
        }
        if (data.length !== size || crc32(data) !== crc) {
            throw unreadable(`${name} doesn't match its recorded size and checksum`)
        }
        entries.push({ name, data })
        offset += 46 + nameLength + extraLength + commentLength
    }
    return entries
}

// `extract_dsym_zip`: entries go under `{output}/{base}/`, keeping only normal path components so
// an entry can't escape the folder.
function extractZip(zip: Buffer, baseName: string, output: string, cwd: string, dryRun: boolean): string[] {
    const folder = join(output, baseName)
    const root = resolve(cwd, folder)
    if (!dryRun) {
        mkdirSync(root, { recursive: true })
    }
    const written: string[] = []
    for (const entry of readZip(zip)) {
        const parts = pathParts(entry.name, process.platform).filter(
            (part) =>
                part !== '' &&
                part !== '.' &&
                part !== '..' &&
                !(process.platform === 'win32' && /^[a-z]:$/i.test(part))
        )
        if (parts.length === 0) {
            continue
        }
        const path = join(folder, ...parts)
        const within = relative(root, resolve(cwd, path))
        if (within.startsWith('..') || isAbsolute(within)) {
            throw new HogError(
                'invalid_symbol_set',
                `The symbol set's zip has an entry outside its folder: ${entry.name}`
            )
        }
        if (!dryRun) {
            mkdirSync(dirname(resolve(cwd, path)), { recursive: true })
            writeFileSync(resolve(cwd, path), entry.data)
        }
        written.push(path)
    }
    return written
}

// `extract_symbol_data`: tries each type in posthog-cli's order. A container whose payload fails
// to decode falls through to the next type, as in posthog-cli.
// Paths in the report are as the caller gave them. Files are written relative to `cwd`, and a dry
// run lists them without writing.
export function extractSymbolSet(
    bytes: Uint8Array,
    baseName: string,
    output: string,
    cwd: string,
    dryRun = false
): ExtractReport {
    const data = Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength)
    if (!dryRun) {
        mkdirSync(resolve(cwd, output), { recursive: true })
    }
    const write = (path: string, data: Uint8Array): void => {
        if (!dryRun) {
            writeFileSync(resolve(cwd, path), data)
        }
    }
    // A container of a known type whose payload fails to decode: posthog-cli reports it as an
    // unknown type, which sends people after the wrong cause.
    let decodeError: { type: number; message: string } | undefined
    const attempt = <T>(read: () => T, type: SymbolDataType): T | undefined => {
        try {
            return read()
        } catch (error) {
            if (!(error instanceof SymbolDataError && error.wrongType !== undefined)) {
                decodeError ??= { type, message: (error as Error).message }
            }
            return undefined
        }
    }
    const pair = attempt(
        () => sourceAndMap(readPayload(data, SymbolDataType.SourceAndMap)),
        SymbolDataType.SourceAndMap
    )
    if (pair) {
        const files = [join(output, `${baseName}.js`), join(output, `${baseName}.js.map`)]
        write(files[0]!, pair.source)
        write(files[1]!, pair.map)
        return { kind: 'sourcemap', output, files }
    }
    const single = (type: SymbolDataType, extension: string, kind: ExtractedKind): ExtractReport | undefined => {
        const payload = attempt(() => {
            const read = readPayload(data, type)
            decodeUtf8(read)
            return read
        }, type)
        if (!payload) {
            return undefined
        }
        const file = join(output, `${baseName}${extension}`)
        write(file, payload)
        return { kind, output, files: [file] }
    }
    const text =
        single(SymbolDataType.HermesMap, '.hbc.map', 'hermes') ??
        single(SymbolDataType.ProguardMapping, '.txt', 'proguard')
    if (text) {
        return text
    }
    const elf = attempt(() => readPayload(data, SymbolDataType.ElfDebugInfo), SymbolDataType.ElfDebugInfo)
    if (elf) {
        return { kind: 'elf', output: join(output, baseName), files: extractZip(elf, baseName, output, cwd, dryRun) }
    }
    let dsym: Buffer
    try {
        dsym = readPayload(data, SymbolDataType.AppleDsym)
    } catch (error) {
        if (error instanceof SymbolDataError && error.wrongType !== undefined) {
            if (decodeError?.type === error.wrongType) {
                throw new HogError(
                    'invalid_symbol_set',
                    `The symbol set is a ${SymbolDataType[decodeError.type]} whose payload hog couldn't read: ${decodeError.message}`
                )
            }
            throw new HogError('unknown_symbol_set', `Unknown symbol data type: ${error.wrongType}`)
        }
        throw new HogError('invalid_symbol_set', `hog couldn't read the symbol set: ${(error as Error).message}`)
    }
    return { kind: 'dsym', output: join(output, baseName), files: extractZip(dsym, baseName, output, cwd, dryRun) }
}

// `urlencoding::encode`: everything except A-Z, a-z, 0-9 and `-._~` is percent-encoded.
function encodeComponent(text: string): string {
    return [...Buffer.from(text, 'utf8')]
        .map((byte) =>
            /[A-Za-z0-9\-._~]/.test(String.fromCharCode(byte)) && byte < 0x80
                ? String.fromCharCode(byte)
                : `%${byte.toString(16).toUpperCase().padStart(2, '0')}`
        )
        .join('')
}

const UUID = /^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$/i

export const isSymbolSetId = (text: string): boolean => UUID.test(text)

// Turns the answers people can act on into errors with a next step. Others keep their message.
async function lookup(request: () => Promise<unknown>, notFound?: string): Promise<unknown> {
    try {
        return await request()
    } catch (error) {
        if (error instanceof ApiFailure && (error.status === 401 || error.status === 403)) {
            throw new HogError(
                'access_denied',
                `PostHog answered ${error.status} to the symbol set lookup.`,
                'Check that the personal API key has the error_tracking:read scope and access to this project.'
            )
        }
        if (notFound && error instanceof ApiFailure && error.status === 404) {
            throw new HogError('symbol_set_not_found', notFound, 'Check the ID, or pass --ref to look it up as a ref.')
        }
        throw error
    }
}

export async function resolveRef(client: SymbolSetClient, reference: string): Promise<string> {
    const found = (await lookup(() =>
        client.api('GET', `error_tracking/symbol_sets/?ref=${encodeComponent(reference)}&limit=1`)
    )) as {
        results?: { id?: string }[]
    }
    const id = found?.results?.[0]?.id
    if (!id) {
        throw new HogError(
            'symbol_set_not_found',
            `No symbol set has the ref ${reference}.`,
            'Check the ref, or pass the symbol set ID.'
        )
    }
    return id
}

export async function downloadSymbolSet(
    client: SymbolSetClient,
    id: string,
    fetcher: RuntimeFetch
): Promise<Uint8Array> {
    if (!isSymbolSetId(id)) {
        throw new HogError('invalid_symbol_set_id', `${id} isn't a symbol set ID.`, 'Symbol set IDs are UUIDs.')
    }
    const { url } = (await lookup(
        () => client.api('GET', `error_tracking/symbol_sets/${id}/download/`),
        `No symbol set has the ID ${id}.`
    )) as { url: string }
    try {
        const response = await fetcher(url, { timeoutMs: DOWNLOAD_TIMEOUT_MS, skipRateLimit: true })
        if (!response.ok) {
            throw new HogError('download_failed', `The symbol set download failed with status ${response.status}.`)
        }
        return new Uint8Array(await response.arrayBuffer())
    } catch (error) {
        if (error instanceof HogError) {
            throw error
        }
        throw new HogError('download_failed', `The symbol set download failed: ${(error as Error).message}`)
    }
}
