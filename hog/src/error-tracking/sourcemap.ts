// A port of the parts of the `sourcemap` crate (9.2.2) and `magic_string` (0.3.4) that posthog-cli
// uses to rewrite a sourcemap after injecting a chunk id. The rewritten map is uploaded and hashed,
// so its bytes must match: token order, VLQ output, the fields the encoder writes, and the quirks
// listed next to the code that reproduces them.
import { formatFloat, isJsonNumber, JsonObject, type JsonNumber, type JsonValue } from './json'

export const NONE = 0xffffffff

export interface Token {
    dstLine: number
    dstCol: number
    srcLine: number
    srcCol: number
    srcId: number
    nameId: number
    isRange: boolean
}

export interface SourceMap {
    file: string | null
    tokens: Token[]
    names: string[]
    sources: string[]
    // Sources with `sourceRoot` prepended, used only when flattening index maps.
    prefixedSources: string[] | null
    sourceRoot: string | null
    sourcesContent: (string | null)[]
    ignoreList: Set<number>
    debugId: string | null
}

export class SourceMapError extends Error {}

const fail = (message: string): never => {
    throw new SourceMapError(message)
}

const BASE64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
const BASE64_VALUES = new Int16Array(128).fill(-1)
for (let index = 0; index < 64; index++) {
    BASE64_VALUES[BASE64.charCodeAt(index)] = index
}

function decodeVlqSegment(segment: string, out: number[]): void {
    let current = 0
    let shift = 0
    for (let index = 0; index < segment.length; index++) {
        const code = segment.charCodeAt(index)
        const digit = code < 128 ? BASE64_VALUES[code]! : -1
        if (digit < 0) {
            fail(`invalid base64 character in mappings`)
        }
        current += (digit & 31) * 2 ** shift
        if (digit & 32) {
            shift += 5
        } else {
            const value = Math.floor(current / 2)
            out.push(current % 2 === 1 ? -value : value)
            current = 0
            shift = 0
        }
    }
    if (shift) {
        fail('VLQ left over')
    }
}

function encodeVlq(out: string[], value: number): void {
    let remaining = value < 0 ? -value * 2 + 1 : value * 2
    do {
        let digit = remaining % 32
        remaining = Math.floor(remaining / 32)
        if (remaining > 0) {
            digit |= 32
        }
        out.push(BASE64[digit]!)
    } while (remaining > 0)
}

const u32 = (value: number): number => value >>> 0

function field(raw: JsonObject, name: string): JsonValue | undefined {
    return raw.entries.get(name)
}

function asU32(value: JsonValue, name: string): number {
    if (!isJsonNumber(value) || value.kind !== 'u' || value.value > 0xffffffffn) {
        fail(`invalid type for ${name}: expected u32`)
    }
    return Number((value as { value: bigint }).value)
}

function optionalString(value: JsonValue | undefined, name: string): string | null {
    if (value === undefined || value === null) {
        return null
    }
    if (typeof value !== 'string') {
        fail(`invalid type for ${name}: expected a string`)
    }
    return value as string
}

function optionalArray(value: JsonValue | undefined, name: string): JsonValue[] | null {
    if (value === undefined || value === null) {
        return null
    }
    if (!Array.isArray(value)) {
        fail(`invalid type for ${name}: expected a sequence`)
    }
    return value as JsonValue[]
}

function optionalU32(value: JsonValue | undefined, name: string): number | null {
    return value === undefined || value === null ? null : asU32(value, name)
}

// Fields serde type-checks even when the decoder ignores them: a wrong type fails the whole map.
function validateExtensions(raw: JsonObject): void {
    for (const offset of optionalArray(field(raw, 'x_facebook_offsets'), 'x_facebook_offsets') ?? []) {
        optionalU32(offset, 'x_facebook_offsets')
    }
    for (const path of optionalArray(field(raw, 'x_metro_module_paths'), 'x_metro_module_paths') ?? []) {
        if (typeof path !== 'string') {
            fail('invalid type for x_metro_module_paths: expected a string')
        }
    }
    for (const source of optionalArray(field(raw, 'x_facebook_sources'), 'x_facebook_sources') ?? []) {
        for (const scope of optionalArray(source, 'x_facebook_sources') ?? []) {
            if (!(scope instanceof JsonObject)) {
                fail('invalid type for x_facebook_sources: expected a struct')
            }
            const mapping = scope as JsonObject
            const names = mapping.entries.get('names')
            if (!Array.isArray(names) || names.some((name) => typeof name !== 'string')) {
                fail('invalid type for x_facebook_sources names')
            }
            if (typeof mapping.entries.get('mappings') !== 'string') {
                fail('invalid type for x_facebook_sources mappings')
            }
        }
    }
}

// `debugid::DebugId::from_str` and its Display: the canonical form written into `debug_id`.
export function canonicalDebugId(text: string): string {
    const invalid = (): never => fail(`invalid value: string ${JSON.stringify(text)}, expected DebugId`)
    if ([...text].some((char) => char.charCodeAt(0) > 0x7f)) {
        invalid()
    }
    const hyphenated = text[8] === '-'
    const hex32 = (value: string): number | null =>
        /^\+?[0-9a-fA-F]+$/.test(value) && Number.parseInt(value.replace('+', ''), 16) <= 0xffffffff
            ? Number.parseInt(value.replace('+', ''), 16)
            : null
    const minPdb = hyphenated ? 10 : 9
    const maxPdb = hyphenated ? 17 : 16
    if (text.length >= minPdb && text.length <= maxPdb) {
        const timestamp = hex32(text.slice(0, 8))
        const appendix = hex32(hyphenated ? text.slice(9) : text.slice(8))
        if (timestamp === null || appendix === null) {
            return invalid()
        }
        const head = timestamp.toString(16).toUpperCase().padStart(8, '0')
        return appendix > 0 ? `${head}-${appendix.toString(16)}` : head
    }
    const uuidLength = hyphenated ? 36 : 32
    const uuidText = text.slice(0, uuidLength)
    const uuidPattern = hyphenated
        ? /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/
        : /^[0-9a-fA-F]{32}$/
    if (uuidText.length !== uuidLength || !uuidPattern.test(uuidText)) {
        return invalid()
    }
    const hex = uuidText.replaceAll('-', '').toLowerCase()
    const uuid = `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
    if (text.length === uuidLength) {
        return uuid
    }
    let appendixText = text.slice(uuidLength)
    if (hyphenated !== appendixText.startsWith('-')) {
        return invalid()
    }
    if (hyphenated) {
        appendixText = appendixText.slice(1)
    }
    const appendix = hex32(appendixText.slice(0, 8))
    if (appendix === null) {
        return invalid()
    }
    return appendix > 0 ? `${uuid}-${appendix.toString(16)}` : uuid
}

function rawDebugId(raw: JsonObject, preferCamelCase: boolean): string | null {
    const snake = optionalString(field(raw, 'debug_id'), 'debug_id')
    const camel = optionalString(field(raw, 'debugId'), 'debugId')
    // serde parses both fields, so an invalid one fails even when the other wins.
    const snakeId = snake === null ? null : canonicalDebugId(snake)
    const camelId = camel === null ? null : canonicalDebugId(camel)
    return preferCamelCase ? (camelId ?? snakeId) : (snakeId ?? camelId)
}

function sortTokens(tokens: Token[]): void {
    // Rust uses `sort_unstable_by_key`. For already sorted input, and for ties within 20 tokens,
    // it agrees with this stable sort. A larger unsorted map with tied positions can order them
    // differently: a known, unreproduced edge case.
    tokens.sort((a, b) => a.dstLine - b.dstLine || a.dstCol - b.dstCol)
}

function prefixSource(root: string, source: string): string {
    const trimmed = root.endsWith('/') ? root.slice(0, -1) : root
    const absolute =
        source !== '' && (source.startsWith('/') || source.startsWith('http:') || source.startsWith('https:'))
    return absolute ? source : `${trimmed}/${source}`
}

function newMap(
    file: string | null,
    tokens: Token[],
    names: string[],
    sources: string[],
    content: (string | null)[] | null
): SourceMap {
    sortTokens(tokens)
    return {
        file,
        tokens,
        names,
        sources,
        prefixedSources: null,
        sourceRoot: null,
        sourcesContent: content ?? [],
        ignoreList: new Set(),
        debugId: null,
    }
}

function setSourceRoot(map: SourceMap, root: string | null): void {
    map.sourceRoot = root
    map.prefixedSources = root ? map.sources.map((source) => prefixSource(root, source)) : null
}

// The `rangeMappings` bitfield of one line: base64 digits, least significant bit first.
function decodeRangeBits(text: string): boolean[] {
    const bits: boolean[] = []
    for (const char of text) {
        const value = char.charCodeAt(0) < 128 ? BASE64_VALUES[char.charCodeAt(0)]! : -1
        if (value < 0) {
            fail(`invalid base64 character ${char} in rangeMappings`)
        }
        for (let bit = 0; bit < 6; bit++) {
            bits.push(((value >> bit) & 1) === 1)
        }
    }
    return bits
}

function fileField(value: JsonValue | undefined): string | null {
    if (value === undefined || value === null) {
        return null
    }
    return typeof value === 'string' ? value : '<invalid>'
}

function numberText(value: JsonNumber): string {
    return value.kind === 'f' ? formatFloat(value.value) : value.value.toString()
}

function decodeRegular(raw: JsonObject): SourceMap {
    optionalU32(field(raw, 'version'), 'version')
    const names = optionalArray(field(raw, 'names'), 'names') ?? []
    const sources = (optionalArray(field(raw, 'sources'), 'sources') ?? []).map((source) =>
        optionalString(source, 'sources')
    )
    const rangeMappings = optionalString(field(raw, 'rangeMappings'), 'rangeMappings') ?? ''
    const mappings = optionalString(field(raw, 'mappings'), 'mappings') ?? ''
    const contentArray = optionalArray(field(raw, 'sourcesContent'), 'sourcesContent')
    const content = contentArray ? contentArray.map((value) => optionalString(value, 'sourcesContent')) : null
    const ignoreList = (optionalArray(field(raw, 'ignoreList'), 'ignoreList') ?? []).map((value) =>
        asU32(value, 'ignoreList')
    )
    const sourceRoot = optionalString(field(raw, 'sourceRoot'), 'sourceRoot')
    validateExtensions(raw)
    const debugId = rawDebugId(raw, false)

    const tokens: Token[] = []
    let sourceId = 0
    let sourceLine = 0
    let sourceColumn = 0
    let nameId = 0
    const numbers: number[] = []
    const rangeLines = rangeMappings.split(';')
    const lines = mappings.split(';')
    for (let line = 0; line < lines.length; line++) {
        const text = lines[line]!
        if (text === '') {
            continue
        }
        const rangeBits = decodeRangeBits(rangeLines[line] ?? '')
        let column = 0
        const segments = text.split(',')
        for (let index = 0; index < segments.length; index++) {
            const segment = segments[index]!
            if (segment === '') {
                continue
            }
            numbers.length = 0
            decodeVlqSegment(segment, numbers)
            if (numbers.length !== 1 && numbers.length !== 4 && numbers.length !== 5) {
                fail(`bad segment size ${numbers.length}`)
            }
            column = u32(column + numbers[0]!)
            let token: Token = {
                dstLine: line,
                dstCol: column,
                srcLine: NONE,
                srcCol: NONE,
                srcId: NONE,
                nameId: NONE,
                isRange: rangeBits[index] ?? false,
            }
            if (numbers.length > 1) {
                sourceId = u32(sourceId + numbers[1]!)
                if (sourceId >= sources.length) {
                    fail(`bad source reference ${sourceId}`)
                }
                sourceLine = u32(sourceLine + numbers[2]!)
                sourceColumn = u32(sourceColumn + numbers[3]!)
                token = { ...token, srcId: sourceId, srcLine: sourceLine, srcCol: sourceColumn }
                if (numbers.length > 4) {
                    nameId = u32(nameId + numbers[4]!)
                    if (nameId >= names.length) {
                        fail(`bad name reference ${nameId}`)
                    }
                    token.nameId = nameId
                }
            }
            tokens.push(token)
        }
    }
    const nameStrings = names.map((name) =>
        typeof name === 'string' ? name : isJsonNumber(name) ? numberText(name) : ''
    )
    const map = newMap(
        fileField(field(raw, 'file')),
        tokens,
        nameStrings,
        sources.map((source) => source ?? ''),
        content
    )
    setSourceRoot(map, sourceRoot)
    map.debugId = debugId
    for (const index of ignoreList) {
        map.ignoreList.add(index)
    }
    return map
}

interface Section {
    line: number
    column: number
    map: SourceMap | null
}

function decodeAny(raw: JsonValue): SourceMap {
    if (!(raw instanceof JsonObject)) {
        return fail('invalid type: expected struct RawSourceMap')
    }
    const sections = field(raw, 'sections')
    if (sections === undefined || sections === null) {
        return decodeRegular(raw)
    }
    optionalU32(field(raw, 'version'), 'version')
    validateExtensions(raw)
    rawDebugId(raw, true)
    const parsed: Section[] = (optionalArray(sections, 'sections') ?? []).map((section) => {
        if (!(section instanceof JsonObject)) {
            return fail('invalid type for sections: expected a struct')
        }
        const offset = section.entries.get('offset')
        if (!(offset instanceof JsonObject)) {
            return fail('invalid type for section offset')
        }
        const line = offset.entries.get('line')
        const column = offset.entries.get('column')
        if (line === undefined || column === undefined) {
            return fail('missing field in section offset')
        }
        optionalString(section.entries.get('url'), 'url')
        const map = section.entries.get('map')
        return {
            line: asU32(line, 'line'),
            column: asU32(column, 'column'),
            map: map === undefined || map === null ? null : decodeAny(map),
        }
    })
    parsed.sort((a, b) => a.line - b.line || a.column - b.column)
    return flatten(fileField(field(raw, 'file')), parsed)
}

// `SourceMapIndex::flatten`: sources and names are deduplicated, tokens offset by their section.
// The flattened map has no debug id.
function flatten(file: string | null, sections: Section[]): SourceMap {
    const sourceIds = new Map<string, number>()
    const sources: string[] = []
    const content: (string | null)[] = []
    const nameIds = new Map<string, number>()
    const names: string[] = []
    const tokens: Token[] = []
    const ignore = new Set<number>()
    for (const section of sections) {
        const map = section.map ?? fail('cannot flatten a section without a map')
        const sectionSourceIds = (map.prefixedSources ?? map.sources).map((source, index) => {
            let id = sourceIds.get(source)
            if (id === undefined) {
                id = sources.length
                sourceIds.set(source, id)
                sources.push(source)
            }
            const text = map.sourcesContent[index] ?? null
            if (text !== null) {
                while (content.length < sources.length) {
                    content.push(null)
                }
                content[id] = text
            }
            return id
        })
        const sectionNameIds = map.names.map((name) => {
            let id = nameIds.get(name)
            if (id === undefined) {
                id = names.length
                nameIds.set(name, id)
                names.push(name)
            }
            return id
        })
        for (const token of map.tokens) {
            const srcId = token.srcId === NONE ? NONE : (sectionSourceIds[token.srcId] ?? NONE)
            tokens.push({
                ...token,
                dstLine: u32(token.dstLine + section.line),
                dstCol: token.dstLine === 0 ? u32(token.dstCol + section.column) : token.dstCol,
                srcId,
                nameId: token.nameId === NONE ? NONE : (sectionNameIds[token.nameId] ?? NONE),
            })
            if (map.ignoreList.has(token.srcId)) {
                ignore.add(srcId)
            }
        }
    }
    const map = newMap(file, tokens, names, sources, content.length > 0 ? content : null)
    for (const index of ignore) {
        map.ignoreList.add(index)
    }
    return map
}

export function decodeSourceMap(raw: JsonValue): SourceMap {
    return decodeAny(raw)
}

// `SourceMap::adjust_mappings`: maps every token through the adjustment's ranges. A range never
// crosses a line, so tokens on lines the adjustment doesn't cover are dropped.
export function adjustMappings(map: SourceMap, adjustment: Token[]): void {
    type Position = [number, number]
    interface Range {
        start: Position
        end: Position
        token: Token
    }
    const before = (a: Position, b: Position): boolean => a[0] < b[0] || (a[0] === b[0] && a[1] < b[1])
    const atMost = (a: Position, b: Position): boolean => !before(b, a)
    const ranges = (tokens: Token[], key: (token: Token) => Position): Range[] => {
        tokens.sort((a, b) => {
            const ka = key(a)
            const kb = key(b)
            return ka[0] - kb[0] || ka[1] - kb[1]
        })
        return tokens.map((token, index) => {
            const start = key(token)
            const next: Position = index + 1 < tokens.length ? key(tokens[index + 1]!) : [Infinity, Infinity]
            const endOfLine: Position = [start[0], Infinity]
            return { start, end: before(next, endOfLine) ? next : endOfLine, token }
        })
    }
    const original = ranges(map.tokens, (token) => [token.dstLine, token.dstCol])
    const adjusted = ranges([...adjustment], (token) => [token.srcLine, token.srcCol])
    map.tokens = []
    if (original.length === 0) {
        return
    }
    let index = 0
    let current = original[0]!
    outer: for (const range of adjusted) {
        const lineDelta = range.token.dstLine - range.token.srcLine
        const columnDelta = range.token.dstCol - range.token.srcCol
        while (atMost(current.end, range.start)) {
            if (++index >= original.length) {
                break outer
            }
            current = original[index]!
        }
        while (before(current.start, range.end)) {
            const [line, column] = before(current.start, range.start) ? range.start : current.start
            map.tokens.push({ ...current.token, dstLine: u32(line + lineDelta), dstCol: u32(column + columnDelta) })
            if (atMost(range.end, current.end)) {
                break
            }
            if (++index >= original.length) {
                break outer
            }
            current = original[index]!
        }
    }
    sortTokens(map.tokens)
}

const sameToken = (a: Token, b: Token): boolean =>
    a.dstLine === b.dstLine &&
    a.dstCol === b.dstCol &&
    a.srcLine === b.srcLine &&
    a.srcCol === b.srcCol &&
    a.srcId === b.srcId &&
    a.nameId === b.nameId &&
    a.isRange === b.isRange

function serializeMappings(map: SourceMap): string {
    const out: string[] = []
    let line = 0
    let column = 0
    let sourceLine = 0
    let sourceColumn = 0
    let nameId = 0
    let sourceId = 0
    map.tokens.forEach((token, index) => {
        if (token.dstLine !== line) {
            column = 0
            while (token.dstLine !== line) {
                out.push(';')
                line++
            }
        } else if (index > 0) {
            if (sameToken(token, map.tokens[index - 1]!)) {
                return
            }
            out.push(',')
        }
        encodeVlq(out, token.dstCol - column)
        column = token.dstCol
        if (token.srcId !== NONE) {
            encodeVlq(out, token.srcId - sourceId)
            sourceId = token.srcId
            encodeVlq(out, token.srcLine - sourceLine)
            sourceLine = token.srcLine
            encodeVlq(out, token.srcCol - sourceColumn)
            sourceColumn = token.srcCol
            if (token.nameId !== NONE && token.nameId < map.names.length) {
                encodeVlq(out, token.nameId - nameId)
                nameId = token.nameId
            }
        }
    })
    return out.join('')
}

function encodeRangeBits(bits: boolean[], out: string[]): void {
    let last = 0
    bits.forEach((bit, index) => {
        if (bit) {
            last = index
        }
    })
    for (let start = 0; start <= last; start += 6) {
        let value = 0
        for (let bit = 0; bit < 6 && start + bit <= last; bit++) {
            if (bits[start + bit]) {
                value |= 1 << bit
            }
        }
        out.push(BASE64[value]!)
    }
}

// `serialize_range_mappings`, quirks included: a range token's bit is set before the line advance,
// so the first token on a new line is indexed from the previous line's first token, and counted in
// that line's bitfield. Duplicate tokens the mappings writer skips still take an index.
function serializeRangeMappings(map: SourceMap): string | null {
    const out: string[] = []
    let previousLine = 0
    let hadRange = false
    let empty = true
    let firstInLine = 0
    let bits: boolean[] = []
    map.tokens.forEach((token, index) => {
        if (token.isRange) {
            hadRange = true
            empty = false
            const position = index - firstInLine
            while (bits.length < position + 1) {
                bits.push(false)
            }
            bits[position] = true
        }
        while (token.dstLine !== previousLine) {
            if (hadRange) {
                encodeRangeBits(bits, out)
                bits = []
            }
            out.push(';')
            previousLine++
            hadRange = false
            firstInLine = index
        }
    })
    if (empty) {
        return null
    }
    if (hadRange) {
        encodeRangeBits(bits, out)
    }
    return out.join('')
}

const u = (value: number): JsonNumber => ({ kind: 'u', value: BigInt(value) })

// `as_raw_sourcemap` as `to_writer` serializes it: version 3, the fields below, and `debug_id` in
// snake_case. Hermes `x_facebook_*` fields are not written.
export function encodeSourceMap(map: SourceMap): JsonObject {
    const out = new JsonObject()
    out.entries.set('version', u(3))
    if (map.file !== null) {
        out.entries.set('file', map.file)
    }
    out.entries.set('sources', [...map.sources])
    if (map.sourceRoot !== null) {
        out.entries.set('sourceRoot', map.sourceRoot)
    }
    let hasContent = false
    const content: JsonValue[] = map.sources.map((_, index) => {
        const text = map.sourcesContent[index] ?? null
        if (text !== null) {
            hasContent = true
        }
        return text
    })
    if (hasContent) {
        out.entries.set('sourcesContent', content)
    }
    out.entries.set('names', [...map.names])
    const ranges = serializeRangeMappings(map)
    if (ranges !== null) {
        out.entries.set('rangeMappings', ranges)
    }
    out.entries.set('mappings', serializeMappings(map))
    if (map.ignoreList.size > 0) {
        out.entries.set('ignoreList', [...map.ignoreList].sort((a, b) => a - b).map(u))
    }
    if (map.debugId !== null) {
        out.entries.set('debug_id', map.debugId)
    }
    return out
}

// magic_string's `generate_map` (hires off) for an edit made of a prepended `intro`, removed byte
// ranges and an appended `outro`. Positions in the original are bytes; columns inside unedited text
// count characters, while the intro and outro widths count bytes.
export function magicStringAdjustment(
    original: Uint8Array,
    intro: string,
    removed: [number, number][],
    outro: string
): Token[] {
    const lineStarts = [0]
    for (let index = 0; index < original.length; index++) {
        if (original[index] === 10) {
            lineStarts.push(index + 1)
        }
    }
    const locate = (offset: number): [number, number] => {
        let low = 0
        let high = lineStarts.length
        while (low < high) {
            const middle = (low + high) >> 1
            if (offset < lineStarts[middle]!) {
                high = middle
            } else {
                low = middle + 1
            }
        }
        return [low - 1, offset - lineStarts[low - 1]!]
    }
    const lines: [number, number, number][][] = []
    let generatedLine = 0
    let generatedColumn = 0
    const push = (segment: [number, number, number]): void => {
        if (generatedLine < lines.length) {
            lines[generatedLine]!.push(segment)
        } else {
            lines.push([segment])
        }
    }
    const advance = (text: string): void => {
        if (!text) {
            return
        }
        const parts = text.split('\n')
        for (let count = parts.length; count > 1; count--) {
            lines.push([])
            generatedColumn = 0
        }
        generatedLine += parts.length - 1
        generatedColumn += Buffer.byteLength(parts.at(-1)!)
    }
    advance(intro)
    const sorted = [...removed].sort((a, b) => a[0] - b[0])
    const chunks: [number, number, boolean][] = []
    let position = 0
    for (const [start, end] of sorted) {
        if (start > position) {
            chunks.push([position, start, false])
        }
        chunks.push([start, end, true])
        position = end
    }
    if (position < original.length || chunks.length === 0) {
        chunks.push([position, original.length, false])
    }
    for (const [start, end, edited] of chunks) {
        if (edited) {
            continue
        }
        let [originalLine, originalColumn] = locate(start)
        let first = true
        for (let index = start; index < end; index++) {
            const byte = original[index]!
            // Continuation bytes belong to the character already counted.
            if ((byte & 0xc0) === 0x80) {
                continue
            }
            if (first) {
                push([generatedColumn, originalLine, originalColumn])
            }
            if (byte === 10) {
                originalLine++
                originalColumn = 0
                generatedLine++
                generatedColumn = 0
                first = true
            } else {
                originalColumn++
                generatedColumn++
                first = false
            }
        }
    }
    advance(outro)
    const tokens: Token[] = []
    lines.forEach((segments, line) =>
        segments.forEach(([column, sourceLine, sourceColumn]) =>
            tokens.push({
                dstLine: line,
                dstCol: column,
                srcLine: sourceLine,
                srcCol: sourceColumn,
                srcId: 0,
                nameId: NONE,
                isRange: false,
            })
        )
    )
    sortTokens(tokens)
    return tokens
}
