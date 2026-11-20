import { readFileSync } from 'node:fs'

import { contentHash, SymbolDataType, symbolDataParts } from '../container'
import { compareUtf8, decodeUtf8, JsonParser, Utf8Writer, writeJson, writeString, type JsonValue } from '../json'
import type { KeepData, StoredData, SymbolSetUpload } from '../upload'
import { isEmptyMap, KnownMapFields, readMapFields, serializeMapIds, type MapIds } from './js'

// React Native with Hermes: Metro writes `.bundle` or `.jsbundle` files that get chunk IDs like
// JavaScript bundles. The Hermes compiler then composes a second map for the bytecode, and that
// composed map is what PostHog symbolicates with.

export const HERMES_BUNDLE_EXTENSIONS = ['.bundle', '.jsbundle'] as const

const FUNCTION_OFFSETS = 'x_hermes_function_offsets'

export function isHermesBundlePath(path: string): boolean {
    return HERMES_BUNDLE_EXTENSIONS.some((extension) => path.endsWith(extension))
}

const EMPTINESS_FIELDS = new Set(['mappings', 'sources', 'names', 'sections'])

const COMMA = Buffer.from(',')
const CLOSE = Buffer.from('}')

// A Hermes map without its tree, which is several times larger than its bytes. hog only moves two
// ids between these maps, so every other field is serialized as soon as it is parsed.
export interface HermesMap extends MapIds {
    composed: boolean
    empty: boolean
    // The other fields as `"key":value` pieces in serde's key order, with the commas between them.
    body: Buffer[]
}

type HermesMapParts = 'ids' | 'all'

class HermesMapBuilder {
    private readonly pieces = new Map<string, Utf8Writer>()
    private readonly emptiness = new Map<string, boolean>()
    private composed = false

    constructor(private readonly parts: HermesMapParts) {}

    field(key: string): Utf8Writer | undefined {
        this.composed ||= key === FUNCTION_OFFSETS
        if (EMPTINESS_FIELDS.has(key)) {
            this.emptiness.set(key, true)
        }
        if (this.parts === 'ids') {
            return undefined
        }
        const piece = new Utf8Writer()
        piece.push(writeString(key), ':')
        this.pieces.set(key, piece)
        return piece
    }

    inspect(key: string, value: JsonValue): void {
        if (EMPTINESS_FIELDS.has(key)) {
            const empty = isEmptyMap((name) => (name === key ? value : undefined))
            this.emptiness.set(key, this.emptiness.get(key)! && empty)
        }
    }

    finish(ids: MapIds): HermesMap {
        const body = [...this.pieces.keys()]
            .sort(compareUtf8)
            .flatMap((key, index) => [...(index === 0 ? [] : [COMMA]), ...this.pieces.get(key)!.finish()])
        return { ...ids, composed: this.composed, empty: [...this.emptiness.values()].every(Boolean), body }
    }
}

function readHermesText(text: string, parts: HermesMapParts): HermesMap {
    const builder = new HermesMapBuilder(parts)
    const ids = readMapFields(text, (key, value) => {
        const piece = builder.field(key)
        builder.inspect(key, value)
        if (piece) {
            writeJson(value, piece)
        }
    })
    return builder.finish(ids)
}

class NotSplittable extends Error {}

const QUOTE = 0x22
const BACKSLASH = 0x5c
const OPEN_BRACKET = 0x5b
const CLOSE_BRACKET = 0x5d
const OPEN_BRACE = 0x7b
const CLOSE_BRACE = 0x7d
const COMMA_BYTE = 0x2c
const COLON = 0x3a
const MIN_SPLIT_ARRAY_BYTES = 256 * 1024
const FIELD_DEPTH = 1

const isJsonWhitespace = (byte: number | undefined): boolean =>
    byte === 0x20 || byte === 0x0a || byte === 0x0d || byte === 0x09

// Reads a map one field at a time, and a large array one element at a time, so the text and the
// tree of the whole map never exist. It only finds where each value starts and ends: `JsonParser`
// still parses every value, so a valid map reads the same either way. On anything unexpected it
// throws, and the caller reads the text whole instead.
class SplitMapReader {
    private readonly builder: HermesMapBuilder

    constructor(
        private readonly bytes: Uint8Array,
        parts: HermesMapParts
    ) {
        this.builder = new HermesMapBuilder(parts)
    }

    read(): HermesMap {
        const bytes = this.bytes
        const known = new KnownMapFields((message) => {
            throw new NotSplittable(message)
        })
        let index = this.skipWhitespace(0)
        this.expect(index++, OPEN_BRACE)
        index = this.skipWhitespace(index)

        if (bytes[index] === CLOSE_BRACE) {
            index++
        } else {
            for (;;) {
                index = this.skipWhitespace(index)
                this.expect(index, QUOTE)
                const keyEnd = this.stringEnd(index)
                const key = this.parse(index, keyEnd, FIELD_DEPTH)
                if (typeof key !== 'string') {
                    throw new NotSplittable('key must be a string')
                }
                index = this.skipWhitespace(keyEnd)
                this.expect(index++, COLON)

                index = this.skipWhitespace(index)
                const end = this.valueEnd(index)
                this.readField(known, key, index, end)

                index = this.skipWhitespace(end)
                const next = bytes[index++]
                if (next === CLOSE_BRACE) {
                    break
                }
                this.expect(index - 1, COMMA_BYTE)
            }
        }

        if (this.skipWhitespace(index) !== bytes.length) {
            throw new NotSplittable('trailing characters')
        }
        return this.builder.finish(known.ids)
    }

    private readField(known: KnownMapFields, key: string, start: number, end: number): void {
        const isLargeArray = this.bytes[start] === OPEN_BRACKET && end - start >= MIN_SPLIT_ARRAY_BYTES
        if (!isLargeArray || KNOWN_KEYS.has(key)) {
            const value = this.parse(start, end, FIELD_DEPTH)
            if (known.take(key, value)) {
                return
            }
            const piece = this.builder.field(key)
            this.builder.inspect(key, value)
            if (piece) {
                writeJson(value, piece)
            }
            return
        }

        const piece = this.builder.field(key)
        piece?.push('[')
        let index = this.skipWhitespace(start + 1)
        for (let count = 0; ; count++) {
            const elementEnd = this.valueEnd(index)
            const element = this.parse(index, elementEnd, FIELD_DEPTH + 1)
            this.builder.inspect(key, [element])
            if (piece) {
                if (count > 0) {
                    piece.push(',')
                }
                writeJson(element, piece)
            }

            index = this.skipWhitespace(elementEnd)
            const next = this.bytes[index++]
            if (next === CLOSE_BRACKET) {
                break
            }
            this.expect(index - 1, COMMA_BYTE)
            index = this.skipWhitespace(index)
        }
        if (index !== end) {
            throw new NotSplittable('the array ends before its value does')
        }
        piece?.push(']')
    }

    // The value starts at the depth it has in the map, so the recursion limit counts from the top.
    private parse(start: number, end: number, depth: number): JsonValue {
        const parser = new JsonParser(decodeUtf8(this.bytes.subarray(start, end)))
        for (let level = 0; level < depth; level++) {
            parser.enter()
        }
        const value = parser.value()
        parser.end()
        return value
    }

    private expect(index: number, byte: number): void {
        if (this.bytes[index] !== byte) {
            throw new NotSplittable(`unexpected byte at ${index}`)
        }
    }

    private skipWhitespace(index: number): number {
        while (isJsonWhitespace(this.bytes[index])) {
            index++
        }
        return index
    }

    private stringEnd(start: number): number {
        const bytes = this.bytes
        for (let quote = bytes.indexOf(QUOTE, start + 1); quote >= 0; quote = bytes.indexOf(QUOTE, quote + 1)) {
            let backslashes = 0
            while (bytes[quote - 1 - backslashes] === BACKSLASH) {
                backslashes++
            }
            if (backslashes % 2 === 0) {
                return quote + 1
            }
        }
        throw new NotSplittable('EOF while parsing a string')
    }

    // Only quotes and brackets are matched: the parser that reads the value decides if it is valid.
    private valueEnd(start: number): number {
        const bytes = this.bytes
        const first = bytes[start]
        if (first === QUOTE) {
            return this.stringEnd(start)
        }
        if (first !== OPEN_BRACE && first !== OPEN_BRACKET) {
            let index = start
            while (
                index < bytes.length &&
                bytes[index] !== COMMA_BYTE &&
                bytes[index] !== CLOSE_BRACE &&
                bytes[index] !== CLOSE_BRACKET &&
                !isJsonWhitespace(bytes[index])
            ) {
                index++
            }
            return index
        }

        let depth = 0
        for (let index = start; index < bytes.length; index++) {
            const byte = bytes[index]
            if (byte === QUOTE) {
                index = this.stringEnd(index) - 1
            } else if (byte === OPEN_BRACE || byte === OPEN_BRACKET) {
                depth++
            } else if ((byte === CLOSE_BRACE || byte === CLOSE_BRACKET) && --depth === 0) {
                return index + 1
            }
        }
        throw new NotSplittable('EOF while parsing a value')
    }
}

const KNOWN_KEYS = new Set(['release_id', 'chunk_id', 'chunkId', 'debugId'])

export const splitHermesMap = (bytes: Uint8Array, parts: HermesMapParts): HermesMap =>
    new SplitMapReader(bytes, parts).read()

export function readHermesMap(bytes: Uint8Array, parts: HermesMapParts): HermesMap {
    try {
        return splitHermesMap(bytes, parts)
    } catch {
        return readHermesText(decodeUtf8(bytes), parts)
    }
}

export function hermesMapBytes(ids: MapIds, body: Uint8Array[] | StoredData): Buffer {
    const head = serializeMapIds(ids).join(',')
    const bodyLength = Array.isArray(body) ? body.reduce((sum, piece) => sum + piece.length, 0) : body.length
    const open = Buffer.from(`{${head}${head && bodyLength > 0 ? ',' : ''}`, 'utf8')
    const bytes = Buffer.allocUnsafe(open.length + bodyLength + CLOSE.length)
    bytes.set(open)

    if (Array.isArray(body)) {
        let offset = open.length
        for (const piece of body) {
            bytes.set(piece, offset)
            offset += piece.length
        }
    } else {
        body.copyTo(bytes, open.length)
    }

    bytes.set(CLOSE, open.length + bodyLength)
    return bytes
}

// posthog-cli refuses to upload a map without this key, so it is what tells a composed map apart
// from Metro's packager map.
export function isComposedMap(path: string): boolean {
    try {
        return readHermesMap(readFileSync(path), 'ids').composed
    } catch {
        return false
    }
}

export const uploadChunkId = (map: MapIds): string | null => map.chunkId ?? map.debugId

export function cloneMetadata(from: MapIds, to: MapIds): void {
    to.chunkId = uploadChunkId(from) ?? to.chunkId
    to.releaseId = from.releaseId
}

export type HermesMapSkip = 'no_chunk_id' | 'empty'

export function hermesSkipReason(map: Pick<HermesMap, keyof MapIds | 'empty'>): HermesMapSkip | undefined {
    if (uploadChunkId(map) === null) {
        return 'no_chunk_id'
    }
    return map.empty ? 'empty' : undefined
}

export function hermesUpload(ids: MapIds, body: Uint8Array[] | StoredData, keep: KeepData): SymbolSetUpload {
    const parts = symbolDataParts(SymbolDataType.HermesMap, hermesMapBytes(ids, body))
    return {
        chunkId: uploadChunkId(ids)!,
        releaseId: ids.releaseId,
        contentHash: contentHash(...parts),
        data: keep(...parts),
    }
}
