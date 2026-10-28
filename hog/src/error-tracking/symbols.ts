import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { inflateRawSync, zstdDecompressSync } from 'node:zlib'

import { HogError } from '@/core/errors'

import { SymbolDataType } from './container'
import { decodeUtf8 } from './json'
import type { SymbolSetClient } from './upload'

const MAGIC = Buffer.from('posthog_error_tracking', 'latin1')

export type ExtractedKind = 'sourcemap' | 'hermes' | 'proguard' | 'elf' | 'dsym'

export interface ExtractReport {
    kind: ExtractedKind
    output: string
    files: string[]
}

// `derive_base_name`: the last path component, without the extension the extracted files get back.
export function deriveBaseName(reference: string): string {
    const parts = reference.split('/').filter((part) => part !== '' && part !== '.')
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
    return name === '' ? 'symbol_set' : name
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
    return zstdDecompressSync(body)
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
    const end = zip.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]))
    if (end < 0 || end + 22 > zip.length) {
        throw new HogError('invalid_symbol_set', "The symbol set's zip archive is unreadable.")
    }
    const count = zip.readUInt16LE(end + 10)
    let offset = zip.readUInt32LE(end + 16)
    const entries: ZipEntry[] = []
    for (let index = 0; index < count; index++) {
        if (offset + 46 > zip.length || zip.readUInt32LE(offset) !== 0x02014b50) {
            throw new HogError('invalid_symbol_set', "The symbol set's zip archive is unreadable.")
        }
        const method = zip.readUInt16LE(offset + 10)
        const compressedSize = zip.readUInt32LE(offset + 20)
        const nameLength = zip.readUInt16LE(offset + 28)
        const extraLength = zip.readUInt16LE(offset + 30)
        const commentLength = zip.readUInt16LE(offset + 32)
        const local = zip.readUInt32LE(offset + 42)
        const name = zip.subarray(offset + 46, offset + 46 + nameLength).toString('utf8')
        const dataStart = local + 30 + zip.readUInt16LE(local + 26) + zip.readUInt16LE(local + 28)
        const raw = zip.subarray(dataStart, dataStart + compressedSize)
        if (method !== 0 && method !== 8) {
            throw new HogError(
                'invalid_symbol_set',
                `The symbol set's zip uses compression method ${method}, which hog can't read.`
            )
        }
        entries.push({ name, data: method === 8 ? inflateRawSync(raw) : raw })
        offset += 46 + nameLength + extraLength + commentLength
    }
    return entries
}

// `extract_dsym_zip`: entries go under `{output}/{base}/`, keeping only normal path components so
// an entry can't escape the folder.
function extractZip(zip: Buffer, baseName: string, output: string, cwd: string): string[] {
    const folder = join(output, baseName)
    mkdirSync(resolve(cwd, folder), { recursive: true })
    const written: string[] = []
    for (const entry of readZip(zip)) {
        const parts = entry.name.split('/').filter((part) => part !== '' && part !== '.' && part !== '..')
        if (parts.length === 0) {
            continue
        }
        const path = join(folder, ...parts)
        mkdirSync(dirname(resolve(cwd, path)), { recursive: true })
        writeFileSync(resolve(cwd, path), entry.data)
        written.push(path)
    }
    return written
}

// `extract_symbol_data`: tries each type in posthog-cli's order. A container whose payload fails
// to decode falls through to the next type, as in posthog-cli.
// Paths in the report are as the caller gave them. Files are written relative to `cwd`.
export function extractSymbolSet(bytes: Uint8Array, baseName: string, output: string, cwd: string): ExtractReport {
    const data = Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength)
    mkdirSync(resolve(cwd, output), { recursive: true })
    const write = (path: string, data: Uint8Array): void => writeFileSync(resolve(cwd, path), data)
    const attempt = <T>(read: () => T): T | undefined => {
        try {
            return read()
        } catch {
            return undefined
        }
    }
    const pair = attempt(() => sourceAndMap(readPayload(data, SymbolDataType.SourceAndMap)))
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
        })
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
    const elf = attempt(() => readPayload(data, SymbolDataType.ElfDebugInfo))
    if (elf) {
        return { kind: 'elf', output: join(output, baseName), files: extractZip(elf, baseName, output, cwd) }
    }
    let dsym: Buffer
    try {
        dsym = readPayload(data, SymbolDataType.AppleDsym)
    } catch (error) {
        if (error instanceof SymbolDataError && error.wrongType !== undefined) {
            throw new HogError('unknown_symbol_set', `Unknown symbol data type: ${error.wrongType}`)
        }
        throw new HogError('invalid_symbol_set', `hog couldn't read the symbol set: ${(error as Error).message}`)
    }
    return { kind: 'dsym', output: join(output, baseName), files: extractZip(dsym, baseName, output, cwd) }
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

export async function resolveRef(client: SymbolSetClient, reference: string): Promise<string> {
    const found = (await client.api(
        'GET',
        `error_tracking/symbol_sets/?ref=${encodeComponent(reference)}&limit=1`
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
    fetcher: typeof fetch
): Promise<Uint8Array> {
    if (!isSymbolSetId(id)) {
        throw new HogError('invalid_symbol_set_id', `${id} isn't a symbol set ID.`, 'Symbol set IDs are UUIDs.')
    }
    const { url } = (await client.api('GET', `error_tracking/symbol_sets/${id}/download/`)) as { url: string }
    const response = await fetcher(url)
    if (!response.ok) {
        throw new HogError('download_failed', `The symbol set download failed with status ${response.status}.`)
    }
    return new Uint8Array(await response.arrayBuffer())
}
