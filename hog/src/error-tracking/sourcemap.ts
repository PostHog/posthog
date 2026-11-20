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

const INITIAL_TOKEN_CAPACITY = 64

// The tokens of a map as one typed array per field. A large bundle has millions of tokens, and an
// object for each one costs several times the 25 bytes a token takes here.
export class TokenList {
    length = 0
    dstLine: Uint32Array
    dstCol: Uint32Array
    srcLine: Uint32Array
    srcCol: Uint32Array
    srcId: Uint32Array
    nameId: Uint32Array
    isRange: Uint8Array

    constructor(capacity = INITIAL_TOKEN_CAPACITY) {
        const size = Math.max(capacity, 1)
        this.dstLine = new Uint32Array(size)
        this.dstCol = new Uint32Array(size)
        this.srcLine = new Uint32Array(size)
        this.srcCol = new Uint32Array(size)
        this.srcId = new Uint32Array(size)
        this.nameId = new Uint32Array(size)
        this.isRange = new Uint8Array(size)
    }

    push(
        dstLine: number,
        dstCol: number,
        srcLine: number,
        srcCol: number,
        srcId: number,
        nameId: number,
        isRange: number
    ): void {
        if (this.length === this.dstLine.length) {
            this.resize(this.length * 2)
        }
        const index = this.length++
        this.dstLine[index] = dstLine
        this.dstCol[index] = dstCol
        this.srcLine[index] = srcLine
        this.srcCol[index] = srcCol
        this.srcId[index] = srcId
        this.nameId[index] = nameId
        this.isRange[index] = isRange
    }

    private resize(capacity: number): void {
        const grown = <T extends Uint32Array | Uint8Array>(column: T): T => {
            const next = new (column.constructor as new (length: number) => T)(capacity)
            next.set(column.subarray(0, this.length))
            return next
        }
        this.dstLine = grown(this.dstLine)
        this.dstCol = grown(this.dstCol)
        this.srcLine = grown(this.srcLine)
        this.srcCol = grown(this.srcCol)
        this.srcId = grown(this.srcId)
        this.nameId = grown(this.nameId)
        this.isRange = grown(this.isRange)
    }

    // Rust uses `sort_unstable_by_key`. For already sorted input, and for ties within 20 tokens,
    // it agrees with this stable sort. A larger unsorted map with tied positions can order them
    // differently: a known, unreproduced edge case.
    sort(): void {
        const { dstLine, dstCol, length } = this
        let sorted = true
        for (let index = 1; index < length && sorted; index++) {
            sorted =
                dstLine[index - 1]! < dstLine[index]! ||
                (dstLine[index - 1] === dstLine[index] && dstCol[index - 1]! <= dstCol[index]!)
        }
        if (sorted) {
            return
        }

        // The index breaks ties, which keeps tokens at the same position in their original order.
        const order = new Uint32Array(length)
        for (let index = 0; index < length; index++) {
            order[index] = index
        }
        order.sort((a, b) => dstLine[a]! - dstLine[b]! || dstCol[a]! - dstCol[b]! || a - b)

        const moved = <T extends Uint32Array | Uint8Array>(column: T): T => {
            const next = new (column.constructor as new (length: number) => T)(column.length)
            for (let index = 0; index < length; index++) {
                next[index] = column[order[index]!]!
            }
            return next
        }
        this.dstLine = moved(this.dstLine)
        this.dstCol = moved(this.dstCol)
        this.srcLine = moved(this.srcLine)
        this.srcCol = moved(this.srcCol)
        this.srcId = moved(this.srcId)
        this.nameId = moved(this.nameId)
        this.isRange = moved(this.isRange)
    }
}

export interface SourceMap {
    file: string | null
    tokens: TokenList
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

const COMMA = 44
const SEMICOLON = 59

// The mappings as bytes. Every character is ASCII, so the string is built from them in one step
// instead of from an array with one entry per character.
class MappingsWriter {
    private bytes = Buffer.allocUnsafe(64 * 1024)
    private length = 0

    byte(value: number): void {
        if (this.length === this.bytes.length) {
            const grown = Buffer.allocUnsafe(this.bytes.length * 2)
            grown.set(this.bytes)
            this.bytes = grown
        }
        this.bytes[this.length++] = value
    }

    vlq(value: number): void {
        let remaining = value < 0 ? -value * 2 + 1 : value * 2
        do {
            let digit = remaining % 32
            remaining = Math.floor(remaining / 32)
            if (remaining > 0) {
                digit |= 32
            }
            this.byte(BASE64.charCodeAt(digit))
        } while (remaining > 0)
    }

    text(): string {
        return this.bytes.toString('latin1', 0, this.length)
    }
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
    tokens: TokenList,
    names: string[],
    sources: string[],
    content: (string | null)[] | null
): SourceMap {
    tokens.sort()
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

function maxSegments(mappings: string): number {
    let separators = 0
    for (let index = 0; index < mappings.length; index++) {
        const code = mappings.charCodeAt(index)
        if (code === COMMA || code === SEMICOLON) {
            separators++
        }
    }
    return separators + 1
}

// Reads the mappings in place. Splitting them into a string per line and per segment first takes
// several times their size, and a bundle's mappings run to tens of megabytes.
function decodeMappings(mappings: string, rangeMappings: string, sourceCount: number, nameCount: number): TokenList {
    const tokens = new TokenList(maxSegments(mappings))
    const rangeLines = rangeMappings === '' ? null : rangeMappings.split(';')
    const numbers: number[] = []
    let sourceId = 0
    let sourceLine = 0
    let sourceColumn = 0
    let nameId = 0

    let lineStart = 0
    for (let line = 0; lineStart <= mappings.length; line++) {
        const found = mappings.indexOf(';', lineStart)
        const lineEnd = found < 0 ? mappings.length : found
        if (lineEnd > lineStart) {
            const rangeBits = rangeLines ? decodeRangeBits(rangeLines[line] ?? '') : null
            let column = 0
            let segment = 0
            let current = 0
            let shift = 0
            numbers.length = 0

            for (let index = lineStart; index <= lineEnd; index++) {
                const code = index < lineEnd ? mappings.charCodeAt(index) : COMMA
                if (code !== COMMA) {
                    const digit = code < 128 ? BASE64_VALUES[code]! : -1
                    if (digit < 0) {
                        fail(`invalid base64 character in mappings`)
                    }
                    current += (digit & 31) * 2 ** shift
                    if (digit & 32) {
                        shift += 5
                    } else {
                        const value = Math.floor(current / 2)
                        numbers.push(current % 2 === 1 ? -value : value)
                        current = 0
                        shift = 0
                    }
                    continue
                }

                // The end of a segment. An empty one still takes an index in the line's range bits.
                const segmentIndex = segment++
                if (index > lineStart && mappings.charCodeAt(index - 1) !== COMMA) {
                    if (shift) {
                        fail('VLQ left over')
                    }
                    if (numbers.length !== 1 && numbers.length !== 4 && numbers.length !== 5) {
                        fail(`bad segment size ${numbers.length}`)
                    }
                    column = u32(column + numbers[0]!)
                    let tokenSourceId = NONE
                    let tokenSourceLine = NONE
                    let tokenSourceColumn = NONE
                    let tokenNameId = NONE
                    if (numbers.length > 1) {
                        sourceId = u32(sourceId + numbers[1]!)
                        if (sourceId >= sourceCount) {
                            fail(`bad source reference ${sourceId}`)
                        }
                        sourceLine = u32(sourceLine + numbers[2]!)
                        sourceColumn = u32(sourceColumn + numbers[3]!)
                        tokenSourceId = sourceId
                        tokenSourceLine = sourceLine
                        tokenSourceColumn = sourceColumn
                        if (numbers.length > 4) {
                            nameId = u32(nameId + numbers[4]!)
                            if (nameId >= nameCount) {
                                fail(`bad name reference ${nameId}`)
                            }
                            tokenNameId = nameId
                        }
                    }
                    tokens.push(
                        line,
                        column,
                        tokenSourceLine,
                        tokenSourceColumn,
                        tokenSourceId,
                        tokenNameId,
                        rangeBits?.[segmentIndex] ? 1 : 0
                    )
                    numbers.length = 0
                }
            }
        }
        lineStart = lineEnd + 1
    }
    return tokens
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

    const tokens = decodeMappings(mappings, rangeMappings, sources.length, names.length)
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

function decodeSection(section: JsonValue): Section {
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
}

const isU32 = (value: JsonValue | undefined): value is JsonNumber =>
    value !== undefined && isJsonNumber(value) && value.kind === 'u' && value.value <= 0xffffffffn

// True when the sections are already in the order the flattening sorts them into, and each one has
// a map. Then a section can be flattened as soon as it is decoded. Otherwise every section is
// decoded first, so an invalid section fails before a missing map does, in the order they come.
function sectionsAreOrdered(sections: JsonValue[]): boolean {
    let lastLine = 0
    let lastColumn = 0
    for (const section of sections) {
        const offset = section instanceof JsonObject ? section.entries.get('offset') : undefined
        const map = section instanceof JsonObject ? section.entries.get('map') : undefined
        const line = offset instanceof JsonObject ? offset.entries.get('line') : undefined
        const column = offset instanceof JsonObject ? offset.entries.get('column') : undefined
        if (!isU32(line) || !isU32(column) || map === undefined || map === null) {
            return false
        }
        const sectionLine = Number(line.value)
        const sectionColumn = Number(column.value)
        if (sectionLine < lastLine || (sectionLine === lastLine && sectionColumn < lastColumn)) {
            return false
        }
        lastLine = sectionLine
        lastColumn = sectionColumn
    }
    return true
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
    const list = optionalArray(sections, 'sections') ?? []
    const flattened = new FlattenedSections()

    // An Expo bundle has a section per module. Holding every decoded section until the last one
    // is read doubles the tokens in memory, so ordered sections are flattened one at a time.
    if (sectionsAreOrdered(list)) {
        for (const section of list) {
            flattened.add(decodeSection(section))
        }
    } else {
        const parsed = list.map(decodeSection)
        parsed.sort((a, b) => a.line - b.line || a.column - b.column)
        parsed.forEach((section) => flattened.add(section))
    }
    return flattened.finish(fileField(field(raw, 'file')))
}

// `SourceMapIndex::flatten`: sources and names are deduplicated, tokens offset by their section.
// The flattened map has no debug id.
class FlattenedSections {
    private readonly sourceIds = new Map<string, number>()
    private readonly sources: string[] = []
    private readonly content: (string | null)[] = []
    private readonly nameIds = new Map<string, number>()
    private readonly names: string[] = []
    private readonly tokens = new TokenList()
    private readonly ignore = new Set<number>()

    add(section: Section): void {
        const { sourceIds, sources, content, nameIds, names, tokens, ignore } = this
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

        const from = map.tokens
        const hasIgnored = map.ignoreList.size > 0
        for (let index = 0; index < from.length; index++) {
            const tokenSourceId = from.srcId[index]!
            const tokenNameId = from.nameId[index]!
            const srcId = tokenSourceId === NONE ? NONE : (sectionSourceIds[tokenSourceId] ?? NONE)
            tokens.push(
                u32(from.dstLine[index]! + section.line),
                from.dstLine[index] === 0 ? u32(from.dstCol[index]! + section.column) : from.dstCol[index]!,
                from.srcLine[index]!,
                from.srcCol[index]!,
                srcId,
                tokenNameId === NONE ? NONE : (sectionNameIds[tokenNameId] ?? NONE),
                from.isRange[index]!
            )
            if (hasIgnored && map.ignoreList.has(tokenSourceId)) {
                ignore.add(srcId)
            }
        }
    }

    finish(file: string | null): SourceMap {
        const map = newMap(file, this.tokens, this.names, this.sources, this.content.length > 0 ? this.content : null)
        for (const index of this.ignore) {
            map.ignoreList.add(index)
        }
        return map
    }
}

export function decodeSourceMap(raw: JsonValue): SourceMap {
    return decodeAny(raw)
}

// `SourceMap::adjust_mappings`: maps every token through the adjustment's ranges. A range never
// crosses a line, so tokens on lines the adjustment doesn't cover are dropped.
export function adjustMappings(map: SourceMap, adjustment: Token[]): void {
    const before = (aLine: number, aColumn: number, bLine: number, bColumn: number): boolean =>
        aLine < bLine || (aLine === bLine && aColumn < bColumn)
    const original = map.tokens
    original.sort()
    const adjusted = [...adjustment].sort((a, b) => a.srcLine - b.srcLine || a.srcCol - b.srcCol)
    // Every range starts at most one clipped copy of a token, on top of the tokens themselves.
    const moved = new TokenList(original.length + adjusted.length)
    map.tokens = moved
    if (original.length === 0) {
        return
    }

    // A token's range runs to the next token, or to the end of its line when the next token is on
    // a later line. A bundle's map has millions of tokens, so the positions stay in plain numbers:
    // an object per token or per comparison costs gigabytes on a large bundle.
    let index = 0
    let startLine = 0
    let startColumn = 0
    let endLine = 0
    let endColumn = 0
    const load = (): void => {
        startLine = original.dstLine[index]!
        startColumn = original.dstCol[index]!
        const hasNext = index + 1 < original.length
        const nextLine = hasNext ? original.dstLine[index + 1]! : Infinity
        const nextColumn = hasNext ? original.dstCol[index + 1]! : Infinity
        const sameLine = before(nextLine, nextColumn, startLine, Infinity)
        endLine = sameLine ? nextLine : startLine
        endColumn = sameLine ? nextColumn : Infinity
    }
    load()

    outer: for (let at = 0; at < adjusted.length; at++) {
        const range = adjusted[at]!
        const rangeStartLine = range.srcLine
        const rangeStartColumn = range.srcCol
        const next = adjusted[at + 1]
        const nextLine = next ? next.srcLine : Infinity
        const nextColumn = next ? next.srcCol : Infinity
        const sameLine = before(nextLine, nextColumn, rangeStartLine, Infinity)
        const rangeEndLine = sameLine ? nextLine : rangeStartLine
        const rangeEndColumn = sameLine ? nextColumn : Infinity
        const lineDelta = range.dstLine - range.srcLine
        const columnDelta = range.dstCol - range.srcCol

        while (!before(rangeStartLine, rangeStartColumn, endLine, endColumn)) {
            if (++index >= original.length) {
                break outer
            }
            load()
        }
        while (before(startLine, startColumn, rangeEndLine, rangeEndColumn)) {
            const clipped = before(startLine, startColumn, rangeStartLine, rangeStartColumn)
            const line = clipped ? rangeStartLine : startLine
            const column = clipped ? rangeStartColumn : startColumn
            moved.push(
                u32(line + lineDelta),
                u32(column + columnDelta),
                original.srcLine[index]!,
                original.srcCol[index]!,
                original.srcId[index]!,
                original.nameId[index]!,
                original.isRange[index]!
            )
            if (!before(endLine, endColumn, rangeEndLine, rangeEndColumn)) {
                break
            }
            if (++index >= original.length) {
                break outer
            }
            load()
        }
    }
    moved.sort()
}

const sameToken = (tokens: TokenList, a: number, b: number): boolean =>
    tokens.dstLine[a] === tokens.dstLine[b] &&
    tokens.dstCol[a] === tokens.dstCol[b] &&
    tokens.srcLine[a] === tokens.srcLine[b] &&
    tokens.srcCol[a] === tokens.srcCol[b] &&
    tokens.srcId[a] === tokens.srcId[b] &&
    tokens.nameId[a] === tokens.nameId[b] &&
    tokens.isRange[a] === tokens.isRange[b]

function serializeMappings(map: SourceMap): string {
    const out = new MappingsWriter()
    const tokens = map.tokens
    let line = 0
    let column = 0
    let sourceLine = 0
    let sourceColumn = 0
    let nameId = 0
    let sourceId = 0
    for (let index = 0; index < tokens.length; index++) {
        const tokenLine = tokens.dstLine[index]!
        if (tokenLine !== line) {
            column = 0
            while (tokenLine !== line) {
                out.byte(SEMICOLON)
                line++
            }
        } else if (index > 0) {
            if (sameToken(tokens, index, index - 1)) {
                continue
            }
            out.byte(COMMA)
        }
        out.vlq(tokens.dstCol[index]! - column)
        column = tokens.dstCol[index]!
        const tokenSourceId = tokens.srcId[index]!
        if (tokenSourceId !== NONE) {
            out.vlq(tokenSourceId - sourceId)
            sourceId = tokenSourceId
            out.vlq(tokens.srcLine[index]! - sourceLine)
            sourceLine = tokens.srcLine[index]!
            out.vlq(tokens.srcCol[index]! - sourceColumn)
            sourceColumn = tokens.srcCol[index]!
            const tokenNameId = tokens.nameId[index]!
            if (tokenNameId !== NONE && tokenNameId < map.names.length) {
                out.vlq(tokenNameId - nameId)
                nameId = tokenNameId
            }
        }
    }
    return out.text()
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
    const tokens = map.tokens
    if (!tokens.isRange.subarray(0, tokens.length).includes(1)) {
        return null
    }
    const out: string[] = []
    let previousLine = 0
    let hadRange = false
    let firstInLine = 0
    let bits: boolean[] = []
    for (let index = 0; index < tokens.length; index++) {
        if (tokens.isRange[index]) {
            hadRange = true
            const position = index - firstInLine
            while (bits.length < position + 1) {
                bits.push(false)
            }
            bits[position] = true
        }
        while (tokens.dstLine[index] !== previousLine) {
            if (hadRange) {
                encodeRangeBits(bits, out)
                bits = []
            }
            out.push(';')
            previousLine++
            hadRange = false
            firstInLine = index
        }
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
