import { createHash } from 'node:crypto'
import { existsSync, readFileSync, realpathSync } from 'node:fs'
import { basename, dirname, extname, isAbsolute, join } from 'node:path'

import { contentHash, sourceAndMapPayload, SymbolDataType, writeSymbolData } from '../container'
import {
    decodeUtf8,
    JsonError,
    JsonObject,
    JsonParser,
    parseJson,
    stringifyJson,
    writeEntries,
    writeString,
    type JsonValue,
} from '../json'
import { adjustMappings, decodeSourceMap, encodeSourceMap, magicStringAdjustment, type Token } from '../sourcemap'
import type { SymbolSetUpload } from '../upload'

// JavaScript bundles and their sourcemaps: a port of posthog-cli's `sourcemaps/content.rs`,
// `source_pairs.rs` and `inject.rs`. The injected files, the uploaded payload and the event-mode
// content hash all come out byte for byte as posthog-cli writes them.

const SNIPPET = `!function(){try{var e="undefined"!=typeof window?window:"undefined"!=typeof global?global:"undefined"!=typeof globalThis?globalThis:"undefined"!=typeof self?self:{},n=(new e.Error).stack;n&&(e._posthogChunkIds=e._posthogChunkIds||{},e._posthogChunkIds[n]="__POSTHOG_CHUNK_ID__")}catch(e){}}();`
const SNIPPET_WITH_RELEASE = `!function(){try{var e="undefined"!=typeof window?window:"undefined"!=typeof global?global:"undefined"!=typeof globalThis?globalThis:"undefined"!=typeof self?self:{};e._posthogReleaseId=e._posthogReleaseId||__POSTHOG_RELEASE_ID__;var n=(new e.Error).stack;n&&(e._posthogChunkIds=e._posthogChunkIds||{},e._posthogChunkIds[n]="__POSTHOG_CHUNK_ID__")}catch(e){}}();`
const COMMENT = '\n//# chunkId=__POSTHOG_CHUNK_ID__'
const QUOTED_CHUNK = '"__POSTHOG_CHUNK_ID__"'
const CHUNK_PLACEHOLDER = '__POSTHOG_CHUNK_ID__'
const RELEASE_PLACEHOLDER = '__POSTHOG_RELEASE_ID__'
const CHUNK_NAMESPACE = Buffer.from('0e9b3c7a5d1f42a8b6c4e2d0f8a17593', 'hex')

export const JS_EXTENSIONS = ['.js', '.mjs', '.cjs'] as const

const replaceAll = (text: string, find: string, replacement: string): string => text.split(find).join(replacement)
const renderChunk = (template: string, chunkId: string): string =>
    replaceAll(template, QUOTED_CHUNK, writeString(chunkId))

function snippet(chunkId: string, releaseId: string | null): string {
    return releaseId === null
        ? renderChunk(SNIPPET, chunkId)
        : replaceAll(renderChunk(SNIPPET_WITH_RELEASE, chunkId), RELEASE_PLACEHOLDER, writeString(releaseId))
}

const comment = (chunkId: string): string => replaceAll(COMMENT, CHUNK_PLACEHOLDER, chunkId)

// Rust's `str::lines`: splits on `\n`, strips a `\r` before each `\n`, drops a final empty line, and
// keeps a bare `\r` at the very end.
export function rustLines(text: string): string[] {
    const parts = text.split('\n')
    const terminated = text.endsWith('\n')
    if (terminated) {
        parts.pop()
    }
    return parts.map((line, index) => (index < parts.length - 1 || terminated ? line.replace(/\r$/, '') : line))
}

// Rust's `str::trim` removes Unicode White_Space, which does not include U+FEFF.
const RUST_WHITESPACE = '[\\t\\n\\v\\f\\r \\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]'
export const rustTrim = (text: string): string =>
    text.replace(new RegExp(`^${RUST_WHITESPACE}+|${RUST_WHITESPACE}+$`, 'g'), '')

export function uuidv5(bytes: Uint8Array): string {
    const hash = createHash('sha1').update(CHUNK_NAMESPACE).update(bytes).digest().subarray(0, 16)
    hash[6] = (hash[6]! & 0x0f) | 0x50
    hash[8] = (hash[8]! & 0x3f) | 0x80
    const hex = hash.toString('hex')
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

// `uuid::Uuid::parse_str`: the forms a bundler debug id must have to be adopted as a chunk id.
export function isUuid(text: string): boolean {
    return /^(?:urn:uuid:)?(?:\{[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{32})$/i.test(
        text
    )
}

// `SourceMapContent`: three known fields, then every other key flattened into a sorted map.
export interface MapContent {
    releaseId: string | null
    chunkId: string | null
    debugId: string | null
    fields: Map<string, JsonValue>
}

// Parses a map like serde's derive: `chunkId` is an alias of `chunk_id`, a repeated known field is an
// error, nulls read as absent, and any other type for those fields is an error.
export function loadMapContent(text: string): MapContent {
    const parser = new JsonParser(text)
    parser.skipWhitespace()
    if (text[parser.index] !== '{') {
        parser.fail('invalid type: expected struct SourceMapContent')
    }
    parser.enter()
    parser.index++
    parser.skipWhitespace()
    const content: MapContent = { releaseId: null, chunkId: null, debugId: null, fields: new Map() }
    const seen = new Set<string>()
    const known = (name: string, value: JsonValue): string | null => {
        if (seen.has(name)) {
            parser.fail(`duplicate field \`${name}\``)
        }
        seen.add(name)
        if (value === null) {
            return null
        }
        if (typeof value !== 'string') {
            parser.fail(`invalid type for ${name}: expected a string`)
        }
        return value as string
    }
    if (text[parser.index] === '}') {
        parser.index++
    } else {
        for (;;) {
            parser.skipWhitespace()
            if (text[parser.index] !== '"') {
                parser.fail('key must be a string')
            }
            const key = parser.string()
            parser.skipWhitespace()
            if (text[parser.index] !== ':') {
                parser.fail('expected `:`')
            }
            parser.index++
            const value = parser.value()
            if (key === 'release_id') {
                content.releaseId = known('release_id', value)
            } else if (key === 'chunk_id' || key === 'chunkId') {
                content.chunkId = known('chunk_id', value)
            } else if (key === 'debugId') {
                content.debugId = known('debugId', value)
            } else {
                content.fields.set(key, value)
            }
            parser.skipWhitespace()
            const next = text[parser.index++]
            if (next === '}') {
                break
            }
            if (next !== ',') {
                parser.fail('expected `,` or `}`')
            }
        }
    }
    parser.leave()
    parser.end()
    return content
}

export function serializeMapContent(content: MapContent): string {
    const head: string[] = []
    if (content.releaseId !== null) {
        head.push(`"release_id":${writeString(content.releaseId)}`)
    }
    if (content.chunkId !== null) {
        head.push(`"chunk_id":${writeString(content.chunkId)}`)
    }
    if (content.debugId !== null) {
        head.push(`"debugId":${writeString(content.debugId)}`)
    }
    const body: string[] = []
    writeEntries([...content.fields.entries()], body)
    const inner = body.join('').slice(1, -1)
    return `{${[...head, ...(inner ? [inner] : [])].join(',')}}`
}

function isEmptyMap(get: (key: string) => JsonValue | undefined): boolean {
    const mappings = get('mappings')
    const sources = get('sources')
    const names = get('names')
    const sections = get('sections')
    return (
        (typeof mappings !== 'string' || mappings === '') &&
        (!Array.isArray(sources) || sources.length === 0) &&
        (!Array.isArray(names) || names.length === 0) &&
        (!Array.isArray(sections) ||
            sections.every((section) => {
                const map = section instanceof JsonObject ? section.entries.get('map') : undefined
                return !(map instanceof JsonObject) || isEmptyMap((key) => map.entries.get(key))
            }))
    )
}

export const isEmptyMapContent = (content: MapContent): boolean => isEmptyMap((key) => content.fields.get(key))

// `urlencoding::decode`: decodes valid `%XX` sequences, leaves malformed ones as they are, and fails
// when the result is not valid UTF-8.
function percentDecode(text: string): string {
    if (!text.includes('%')) {
        return text
    }
    const raw = Buffer.from(text, 'utf8')
    const bytes = Buffer.alloc(raw.length)
    let length = 0
    for (let index = 0; index < raw.length; index++) {
        const high = hexValue(raw[index + 1])
        const low = hexValue(raw[index + 2])
        if (raw[index] === 0x25 && high !== undefined && low !== undefined) {
            bytes[length++] = high * 16 + low
            index += 2
        } else {
            bytes[length++] = raw[index]!
        }
    }
    return decodeUtf8(bytes.subarray(0, length))
}

function hexValue(byte: number | undefined): number | undefined {
    if (byte === undefined) {
        return undefined
    }
    const digit = Number.parseInt(String.fromCharCode(byte), 16)
    return Number.isNaN(digit) ? undefined : digit
}

export function sourceMappingReference(source: string): string | undefined {
    const lines = rustLines(source)
    for (let index = lines.length - 1; index >= 0; index--) {
        const line = rustTrim(lines[index]!)
        for (const prefix of ['//# sourceMappingURL=', '//@ sourceMappingURL=']) {
            if (line.startsWith(prefix)) {
                return line.slice(prefix.length)
            }
        }
    }
    return undefined
}

// The candidates posthog-cli tries, in order: the referenced path, the reference with the public
// path prefix stripped, and `<file>.map` next to the bundle.
export function findSourceMap(
    sourcePath: string,
    reference: string | undefined,
    publicPathPrefix: string | undefined
): string | undefined {
    const folder = dirname(sourcePath)
    const candidates: string[] = []
    if (reference !== undefined) {
        const decoded = percentDecode(reference)
        const resolve = (path: string): string => (isAbsolute(path) ? path : join(folder, path))
        candidates.push(resolve(decoded))
        if (publicPathPrefix !== undefined) {
            for (const prefix of [publicPathPrefix, `${publicPathPrefix}/`]) {
                if (decoded.startsWith(prefix)) {
                    candidates.push(resolve(decoded.slice(prefix.length)))
                }
            }
        }
    }
    const extension = extname(sourcePath)
    candidates.push(extension ? `${sourcePath.slice(0, -extension.length)}${extension}.map` : `${sourcePath}.map`)
    return candidates.find((candidate) => existsSync(candidate))
}

export function isJsBundle(
    path: string,
    publicPathPrefix: string | undefined,
    extensions: readonly string[] = JS_EXTENSIONS
): boolean {
    const name = basename(path)
    // Rust's `Path::extension` gives no extension for a file named `.js`.
    if (name.lastIndexOf('.') === 0 || !extensions.some((extension) => name.endsWith(extension))) {
        return false
    }
    try {
        return (
            findSourceMap(path, sourceMappingReference(decodeUtf8(readFileSync(path))), publicPathPrefix) !== undefined
        )
    } catch {
        return false
    }
}

export class SourcePair {
    constructor(
        readonly sourcePath: string,
        public source: string,
        readonly mapPath: string,
        public map: MapContent
    ) {}

    clone(): SourcePair {
        return new SourcePair(this.sourcePath, this.source, this.mapPath, {
            ...this.map,
            fields: new Map(this.map.fields),
        })
    }

    private commentValue(prefix: string): string | null {
        const lines = rustLines(this.source)
        for (let index = lines.length - 1; index >= 0; index--) {
            const line = lines[index]!
            if (line.startsWith(prefix)) {
                return line.slice(line.indexOf('=') + 1)
            }
        }
        return null
    }

    chunkId(): string | null {
        return this.commentValue('//# chunkId=')
    }

    sourceDebugId(): string | null {
        return this.commentValue('//# debugId=')
    }

    debugId(): string | null {
        return this.sourceDebugId() ?? this.map.debugId
    }

    // Where the release snippet sits, if the source carries one for `chunkId`. The release id
    // between the snippet halves must be at most 256 bytes, like posthog-cli's search.
    releaseSnippet(
        chunkId: string
    ): { start: number; end: number; releaseStart: number; releaseEnd: number } | undefined {
        const split = SNIPPET_WITH_RELEASE.indexOf(RELEASE_PLACEHOLDER)
        const prefix = SNIPPET_WITH_RELEASE.slice(0, split)
        const suffix = renderChunk(SNIPPET_WITH_RELEASE.slice(split + RELEASE_PLACEHOLDER.length), chunkId)
        const start = this.source.indexOf(prefix)
        if (start < 0) {
            return undefined
        }
        const releaseStart = start + prefix.length
        const length = this.source.slice(releaseStart).indexOf(suffix)
        if (length < 0 || Buffer.byteLength(this.source.slice(releaseStart, releaseStart + length)) > 256) {
            return undefined
        }
        return { start, end: releaseStart + length + suffix.length, releaseStart, releaseEnd: releaseStart + length }
    }

    injectedReleaseId(): string | null {
        const chunkId = this.chunkId()
        const span = chunkId === null ? undefined : this.releaseSnippet(chunkId)
        if (!span) {
            return null
        }
        try {
            const value = parseJson(this.source.slice(span.releaseStart, span.releaseEnd))
            return typeof value === 'string' ? value : null
        } catch {
            return null
        }
    }

    // `apply_adjustment`: decode the map with the sourcemap crate rules, move every token through
    // the adjustment, write it back, then keep the old ids and any old keys the writer dropped.
    private applyAdjustment(adjustment: Token[]): void {
        const decoded = decodeSourceMap(parseJson(serializeMapContent(this.map)))
        adjustMappings(decoded, adjustment)
        const fresh = loadMapContent(stringifyJson(encodeSourceMap(decoded)))
        fresh.chunkId = this.map.chunkId
        fresh.releaseId = this.map.releaseId
        fresh.debugId = this.map.debugId
        for (const [key, value] of this.map.fields) {
            if (key !== 'sections' && !fresh.fields.has(key)) {
                fresh.fields.set(key, value)
            }
        }
        this.map = fresh
    }

    addChunkId(chunkId: string, releaseId: string | null): void {
        if (this.chunkId() !== null) {
            throw new Error('Chunk ID already set')
        }
        const intro = snippet(chunkId, releaseId)
        const outro = comment(chunkId)
        const adjustment = magicStringAdjustment(Buffer.from(this.source, 'utf8'), intro, [], outro)
        this.source = intro + this.source + outro
        // A map that already carries a chunk id is left alone, even when the source had none.
        if (this.map.chunkId === null) {
            this.applyAdjustment(adjustment)
            this.map.chunkId = chunkId
        }
    }

    removeChunkId(chunkId: string): void {
        if (this.chunkId() !== chunkId) {
            throw new Error('Chunk ID mismatch')
        }
        const bytes = Buffer.from(this.source, 'utf8')
        const removed: [number, number][] = []
        const tail = Buffer.from(comment(chunkId), 'utf8')
        const commentAt = bytes.indexOf(tail)
        if (commentAt >= 0) {
            removed.push([commentAt, commentAt + tail.length])
        }
        const plain = Buffer.from(renderChunk(SNIPPET, chunkId), 'utf8')
        const snippetAt = bytes.indexOf(plain)
        if (snippetAt >= 0) {
            removed.push([snippetAt, snippetAt + plain.length])
        } else {
            const span = this.releaseSnippet(chunkId)
            if (span) {
                const start = Buffer.byteLength(this.source.slice(0, span.start))
                removed.push([start, start + Buffer.byteLength(this.source.slice(span.start, span.end))])
            }
        }
        const adjustment = magicStringAdjustment(bytes, '', removed, '')
        let out = bytes
        for (const [start, end] of [...removed].sort((a, b) => b[0] - a[0])) {
            out = Buffer.concat([out.subarray(0, start), out.subarray(end)])
        }
        this.source = decodeUtf8(out)
        this.applyAdjustment(adjustment)
        this.map.chunkId = null
    }

    sourceFingerprint(): string {
        return contentHash(this.source)
    }

    mapFingerprint(): string {
        return contentHash(serializeMapContent(this.map))
    }
}

export type Skip = { path: string; reason: string }

export function readPair(path: string, publicPathPrefix: string | undefined, skipped: Skip[]): SourcePair | undefined {
    let source: string
    let canonical: string
    try {
        canonical = realpathSync(path)
        source = decodeUtf8(readFileSync(canonical))
    } catch (error) {
        skipped.push({ path, reason: `failed to read source: ${(error as Error).message}` })
        return undefined
    }
    let mapPath: string | undefined
    try {
        mapPath = findSourceMap(canonical, sourceMappingReference(source), publicPathPrefix)
    } catch {
        skipped.push({ path, reason: 'the sourcemap reference is not valid UTF-8 once decoded' })
        return undefined
    }
    if (mapPath === undefined) {
        return undefined
    }
    let map: MapContent
    try {
        map = loadMapContent(decodeUtf8(readFileSync(mapPath)))
    } catch (error) {
        skipped.push({
            path,
            reason: `failed to read sourcemap: ${error instanceof JsonError ? error.message : (error as Error).message}`,
        })
        return undefined
    }
    // posthog-cli would rewrite any JSON object the reference names, such as a settings file next to
    // the build. A sourcemap always has `mappings`, or `sections` when it is an index map.
    if (!map.fields.has('mappings') && !map.fields.has('sections')) {
        skipped.push({ path, reason: "the file its sourceMappingURL names isn't a sourcemap: it has no mappings" })
        return undefined
    }
    return new SourcePair(canonical, source, mapPath, map)
}

const FILE_PATH_TOKEN = '\u0001file-path\u0001'
const isIdentifierChar = (codePoint: number): boolean =>
    /[\p{Alphabetic}\p{N}_$]/u.test(String.fromCodePoint(codePoint))
const isPathChar = (codePoint: number): boolean =>
    isIdentifierChar(codePoint) || '-./\\~@+'.includes(String.fromCodePoint(codePoint))

// `without_file_paths`: replaces every script path (ending in .js, .mjs or .cjs) with a fixed token,
// so a rebuild that only renames hashed chunk files keeps the same event-mode content hash.
export function withoutFilePaths(text: string): string {
    const out: string[] = []
    let copied = 0
    let searched = 0
    let changed = false
    for (;;) {
        const js = text.indexOf('js', searched)
        if (js < 0) {
            break
        }
        const end = js + 2
        searched = end
        let extension: number
        if (js >= 1 && text[js - 1] === '.') {
            extension = js - 1
        } else if (js >= 2 && (text[js - 1] === 'm' || text[js - 1] === 'c') && text[js - 2] === '.') {
            extension = js - 2
        } else {
            continue
        }
        if (end < text.length && isIdentifierChar(text.codePointAt(end)!)) {
            continue
        }
        let start = -1
        let index = extension
        while (index > copied) {
            const code = text.charCodeAt(index - 1)
            let codePoint = code
            let width = 1
            if (code >= 0xdc00 && code <= 0xdfff && index - 2 >= copied) {
                const high = text.charCodeAt(index - 2)
                if (high >= 0xd800 && high <= 0xdbff) {
                    codePoint = text.codePointAt(index - 2)!
                    width = 2
                }
            }
            if (!isPathChar(codePoint)) {
                break
            }
            index -= width
            start = index
        }
        if (start < 0) {
            continue
        }
        changed = true
        out.push(text.slice(copied, start), FILE_PATH_TOKEN)
        copied = end
    }
    if (!changed) {
        return text
    }
    out.push(text.slice(copied))
    return out.join('')
}

export type ReleaseMode = 'event' | 'symbol-set'

// `into_upload`: the payload is the injected source and its map. In event mode the content hash
// covers the pristine pair instead (injection removed, script paths replaced), so it stays the
// same across releases and rebuilds.
export function pairUpload(original: SourcePair, mode: ReleaseMode): SymbolSetUpload {
    const pair = original.clone()
    const injected = pair.chunkId()
    const chunkId = injected ?? pair.debugId()
    if (chunkId === null) {
        throw new Error(`Chunk ID or debug ID not found in ${pair.sourcePath}`)
    }
    const source = pair.source
    const map = serializeMapContent(pair.map)
    const data = writeSymbolData(
        SymbolDataType.SourceAndMap,
        sourceAndMapPayload(Buffer.from(source, 'utf8'), Buffer.from(map, 'utf8'))
    )
    let hash: string | undefined
    if (mode === 'event') {
        let variant: string
        if (injected !== null) {
            variant = pair.releaseSnippet(chunkId) ? 'with-release' : 'chunk-id-only'
            pair.removeChunkId(chunkId)
        } else {
            variant = 'native-debug-id'
        }
        const file = pair.map.fields.get('file')
        if (typeof file === 'string') {
            pair.map.fields.set('file', withoutFilePaths(file))
        }
        hash = contentHash(withoutFilePaths(pair.source), '\0', serializeMapContent(pair.map), '\0', variant)
    }
    return { chunkId, releaseId: pair.map.releaseId, data, contentHash: hash }
}
