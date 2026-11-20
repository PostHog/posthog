import { basename } from 'node:path'

import { JsonObject, JsonParser, writeEntries, writeString, type JsonValue } from '../json'

// What hog itself reads of JavaScript bundles and sourcemaps: which names count as bundles, and
// the sourcemap fields the Hermes commands change. hog-worker does the rest.

export const JS_EXTENSIONS = ['.js', '.mjs', '.cjs'] as const

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

// Rust's `Path::extension` gives no extension for a file named `.js`.
export function hasBundleName(path: string, extensions: readonly string[]): boolean {
    const name = basename(path)
    return name.lastIndexOf('.') !== 0 && extensions.some((extension) => name.endsWith(extension))
}

// `intended` marks a file hog left out on purpose, such as one an ignore pattern matches, so the upload
// still counts as complete.
export type Skip = { path: string; reason: string; intended?: true }

export type ReleaseMode = 'event' | 'symbol-set'
