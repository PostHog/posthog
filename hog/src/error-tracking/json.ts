// A JSON reader and writer that produce the same bytes as serde_json 1.0.145 with default features,
// which posthog-cli uses to read and rewrite sourcemaps. The bytes feed uploads and content hashes,
// so `JSON.parse` and `JSON.stringify` are not enough: they reorder integer-like keys, round large
// integers, print `1.0` as `1`, and accept lone surrogates and `1e400`, which serde rejects.

export type JsonNumber = { kind: 'u' | 'i'; value: bigint } | { kind: 'f'; value: number }

// serde_json without `preserve_order` stores objects in a BTreeMap, so output keys are sorted by
// their UTF-8 bytes. A Map keeps the values; the writer sorts.
export class JsonObject {
    readonly entries = new Map<string, JsonValue>()
}

export type JsonValue = null | boolean | string | JsonNumber | JsonValue[] | JsonObject

export function isJsonNumber(value: JsonValue | undefined): value is JsonNumber {
    return value !== null && typeof value === 'object' && !Array.isArray(value) && !(value instanceof JsonObject)
}

const POW10 = Array.from({ length: 309 }, (_, index) => Number(`1e${index}`))
const U64_MAX = (1n << 64n) - 1n
const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/
// serde_json's recursion limit: nesting deeper than this is an error.
const MAX_DEPTH = 128

export class JsonError extends Error {}

const strictUtf8 = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true })

// serde_json::from_slice rejects invalid UTF-8 and treats a BOM as an unexpected character.
export function decodeUtf8(bytes: Uint8Array): string {
    return strictUtf8.decode(bytes)
}

export class JsonParser {
    index = 0
    private depth = 0

    constructor(readonly text: string) {}

    fail(message: string): never {
        throw new JsonError(`${message} at character ${this.index}`)
    }

    skipWhitespace(): void {
        const text = this.text
        for (;;) {
            const code = text.charCodeAt(this.index)
            if (code !== 32 && code !== 10 && code !== 13 && code !== 9) {
                return
            }
            this.index++
        }
    }

    value(): JsonValue {
        this.skipWhitespace()
        const char = this.text[this.index]
        switch (char) {
            case '{':
                return this.object()
            case '[':
                return this.array()
            case '"':
                return this.string()
            case 't':
                return this.literal('true', true)
            case 'f':
                return this.literal('false', false)
            case 'n':
                return this.literal('null', null)
            case '-':
                this.index++
                return this.number(false)
            default:
                if (char !== undefined && char >= '0' && char <= '9') {
                    return this.number(true)
                }
                return this.fail('expected value')
        }
    }

    enter(): void {
        if (++this.depth >= MAX_DEPTH) {
            this.fail('recursion limit exceeded')
        }
    }

    leave(): void {
        this.depth--
    }

    private literal(word: string, value: JsonValue): JsonValue {
        if (!this.text.startsWith(word, this.index)) {
            this.fail('expected ident')
        }
        this.index += word.length
        return value
    }

    private object(): JsonObject {
        this.enter()
        this.index++
        const object = new JsonObject()
        this.skipWhitespace()
        if (this.text[this.index] === '}') {
            this.index++
            this.leave()
            return object
        }
        for (;;) {
            this.skipWhitespace()
            if (this.text[this.index] !== '"') {
                this.fail('key must be a string')
            }
            const key = this.string()
            this.skipWhitespace()
            if (this.text[this.index] !== ':') {
                this.fail('expected `:`')
            }
            this.index++
            // A repeated key keeps the last value, as in serde_json's Value.
            object.entries.set(key, this.value())
            this.skipWhitespace()
            const next = this.text[this.index++]
            if (next === '}') {
                break
            }
            if (next !== ',') {
                this.fail('expected `,` or `}`')
            }
        }
        this.leave()
        return object
    }

    private array(): JsonValue[] {
        this.enter()
        this.index++
        const array: JsonValue[] = []
        this.skipWhitespace()
        if (this.text[this.index] === ']') {
            this.index++
            this.leave()
            return array
        }
        for (;;) {
            array.push(this.value())
            this.skipWhitespace()
            const next = this.text[this.index++]
            if (next === ']') {
                break
            }
            if (next !== ',') {
                this.fail('expected `,` or `]`')
            }
        }
        this.leave()
        return array
    }

    string(): string {
        const text = this.text
        const start = this.index
        let end = start + 1
        let escaped = false
        for (;;) {
            const code = text.charCodeAt(end)
            if (Number.isNaN(code)) {
                this.fail('EOF while parsing a string')
            }
            if (code === 34) {
                break
            }
            if (code === 92) {
                escaped = true
                end += 2
                continue
            }
            if (code < 0x20) {
                this.fail('control character found while parsing a string')
            }
            end++
        }
        this.index = end + 1
        if (!escaped) {
            return text.slice(start + 1, end)
        }
        const decoded = JSON.parse(text.slice(start, end + 1)) as string
        if (LONE_SURROGATE.test(decoded)) {
            this.fail('lone leading surrogate in hex escape')
        }
        return decoded
    }

    private digit(): number {
        const code = this.text.charCodeAt(this.index)
        return code >= 48 && code <= 57 ? code - 48 : -1
    }

    // serde_json's number parser without `float_roundtrip`: the digits accumulate into a u64
    // significand, then one multiply or divide by a power of ten. It is not always correctly rounded,
    // which is why `Number(text)` can disagree with it.
    private number(positive: boolean): JsonNumber {
        let digit = this.digit()
        if (digit < 0) {
            this.fail('invalid number')
        }
        this.index++
        let significand = BigInt(digit)
        if (digit === 0) {
            if (this.digit() >= 0) {
                this.fail('invalid number')
            }
            return this.afterInteger(positive, 0n)
        }
        for (;;) {
            digit = this.digit()
            if (digit < 0) {
                return this.afterInteger(positive, significand)
            }
            const next = significand * 10n + BigInt(digit)
            if (next > U64_MAX) {
                return { kind: 'f', value: this.longInteger(positive, significand) }
            }
            this.index++
            significand = next
        }
    }

    private longInteger(positive: boolean, significand: bigint): number {
        let exponent = 0
        while (this.digit() >= 0) {
            this.index++
            exponent++
        }
        const char = this.text[this.index]
        if (char === '.') {
            return this.decimal(positive, significand, exponent)
        }
        if (char === 'e' || char === 'E') {
            return this.exponent(positive, significand, exponent)
        }
        return this.fromParts(positive, significand, exponent)
    }

    private afterInteger(positive: boolean, significand: bigint): JsonNumber {
        const char = this.text[this.index]
        if (char === '.') {
            return { kind: 'f', value: this.decimal(positive, significand, 0) }
        }
        if (char === 'e' || char === 'E') {
            return { kind: 'f', value: this.exponent(positive, significand, 0) }
        }
        if (positive) {
            return { kind: 'u', value: significand }
        }
        // serde_json keeps a negative integer when it fits i64, and makes -0 a float.
        const negated = BigInt.asIntN(64, -BigInt.asIntN(64, significand))
        if (negated >= 0n) {
            return { kind: 'f', value: -Number(significand) }
        }
        return { kind: 'i', value: negated }
    }

    private decimal(positive: boolean, significand: bigint, exponentBefore: number): number {
        this.index++
        let after = 0
        let digit
        while ((digit = this.digit()) >= 0) {
            const next = significand * 10n + BigInt(digit)
            if (next > U64_MAX) {
                while (this.digit() >= 0) {
                    this.index++
                }
                const char = this.text[this.index]
                if (char === 'e' || char === 'E') {
                    return this.exponent(positive, significand, exponentBefore + after)
                }
                return this.fromParts(positive, significand, exponentBefore + after)
            }
            this.index++
            significand = next
            after--
        }
        if (after === 0) {
            this.fail('invalid number')
        }
        const char = this.text[this.index]
        if (char === 'e' || char === 'E') {
            return this.exponent(positive, significand, exponentBefore + after)
        }
        return this.fromParts(positive, significand, exponentBefore + after)
    }

    private exponent(positive: boolean, significand: bigint, start: number): number {
        this.index++
        let positiveExponent = true
        if (this.text[this.index] === '+') {
            this.index++
        } else if (this.text[this.index] === '-') {
            this.index++
            positiveExponent = false
        }
        let digit = this.digit()
        if (digit < 0) {
            this.fail('invalid number')
        }
        this.index++
        let exponent = digit
        while ((digit = this.digit()) >= 0) {
            this.index++
            if (exponent * 10 + digit > 2147483647) {
                if (significand !== 0n && positiveExponent) {
                    this.fail('number out of range')
                }
                while (this.digit() >= 0) {
                    this.index++
                }
                return positive ? 0 : -0
            }
            exponent = exponent * 10 + digit
        }
        const total = positiveExponent ? start + exponent : start - exponent
        return this.fromParts(positive, significand, Math.max(-2147483648, Math.min(2147483647, total)))
    }

    private fromParts(positive: boolean, significand: bigint, exponent: number): number {
        let value = Number(significand)
        for (;;) {
            const magnitude = Math.abs(exponent)
            if (magnitude < POW10.length) {
                if (exponent >= 0) {
                    value *= POW10[magnitude]!
                    if (!Number.isFinite(value)) {
                        this.fail('number out of range')
                    }
                } else {
                    value /= POW10[magnitude]!
                }
                break
            }
            if (value === 0) {
                break
            }
            if (exponent >= 0) {
                this.fail('number out of range')
            }
            value /= 1e308
            exponent += 308
        }
        return positive ? value : -value
    }

    end(): void {
        this.skipWhitespace()
        if (this.index !== this.text.length) {
            this.fail('trailing characters')
        }
    }
}

export function parseJson(text: string): JsonValue {
    const parser = new JsonParser(text)
    const value = parser.value()
    parser.end()
    return value
}

// ryu's `format_finite` layout over JavaScript's shortest round-trip digits.
export function formatFloat(value: number): string {
    const sign = value < 0 || Object.is(value, -0) ? '-' : ''
    if (value === 0) {
        return `${sign}0.0`
    }
    const [mantissa = '', exponentText = '0'] = Math.abs(value).toExponential().split('e')
    const digits = mantissa.replace('.', '')
    const length = digits.length
    const kk = Number(exponentText) + 1
    const k = kk - length
    let out: string
    if (k >= 0 && kk <= 16) {
        out = `${digits}${'0'.repeat(k)}.0`
    } else if (kk > 0 && kk <= 16) {
        out = `${digits.slice(0, kk)}.${digits.slice(kk)}`
    } else if (kk > -5 && kk <= 0) {
        out = `0.${'0'.repeat(-kk)}${digits}`
    } else if (length === 1) {
        out = `${digits}e${kk - 1}`
    } else {
        out = `${digits[0]}.${digits.slice(1)}e${kk - 1}`
    }
    return sign + out
}

export function compareUtf8(a: string, b: string): number {
    return Buffer.compare(Buffer.from(a, 'utf8'), Buffer.from(b, 'utf8'))
}

// serde_json escapes the same characters as JSON.stringify for strings without lone surrogates,
// which the parser already rejects.
export function writeString(value: string): string {
    return JSON.stringify(value)
}

export function writeJson(value: JsonValue, parts: string[] = []): string[] {
    if (value === null) {
        parts.push('null')
    } else if (value === true) {
        parts.push('true')
    } else if (value === false) {
        parts.push('false')
    } else if (typeof value === 'string') {
        parts.push(writeString(value))
    } else if (Array.isArray(value)) {
        parts.push('[')
        value.forEach((item, index) => {
            if (index > 0) {
                parts.push(',')
            }
            writeJson(item, parts)
        })
        parts.push(']')
    } else if (value instanceof JsonObject) {
        writeEntries([...value.entries], parts)
    } else {
        parts.push(value.kind === 'f' ? formatFloat(value.value) : value.value.toString())
    }
    return parts
}

export function writeEntries(entries: [string, JsonValue][], parts: string[]): void {
    parts.push('{')
    entries
        .sort((a, b) => compareUtf8(a[0], b[0]))
        .forEach(([key, item], index) => {
            if (index > 0) {
                parts.push(',')
            }
            parts.push(writeString(key), ':')
            writeJson(item, parts)
        })
    parts.push('}')
}

export function stringifyJson(value: JsonValue): string {
    return writeJson(value).join('')
}
