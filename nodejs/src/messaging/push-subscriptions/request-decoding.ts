import { gunzipSync } from 'zlib'

/** Mirrors Django's `decompress` / `load_data_from_request`, which every released SDK is already
 * talking to. A body Django accepts and this rejects is a device that never registers, and the SDK
 * re-posts it on every app open for the life of the install, so the decoding has to match rather
 * than be merely reasonable.
 */

export class RequestParsingError extends Error {}

/** Raised when a body with no declared compression parsed as neither JSON nor gzip. Django
 * distinguishes it from RequestParsingError; the view answers both the same way. */
export class UnspecifiedCompressionFallbackParsingError extends Error {}

const GZIP_COMPRESSIONS = new Set(['gzip', 'gzip-js'])
const BODY_CONTENT_TYPES = new Set(['', 'text/plain', 'application/json'])

export type RawRequest = {
    method: string
    body: Buffer
    contentType?: string
    contentEncoding?: string
    /** Parsed from the URL. Django reads `compression` from the query string for POST. */
    query?: URLSearchParams
}

/** The decoded body, plus the form fields Django's `get_token` reads directly off `request.POST`. */
export type DecodedRequest = {
    data: unknown
    form?: URLSearchParams
}

export function decodeRequest(request: RawRequest): DecodedRequest {
    const contentType = (request.contentType ?? '').split(';')[0].trim().toLowerCase()
    const isForm = request.method === 'POST' && !BODY_CONTENT_TYPES.has(contentType)
    const form = isForm ? parseForm(request.body, contentType) : undefined

    // DELETE never reads form fields: Django's `load_data_from_request` only inspects the body for
    // POST, so the view decompresses `request.body` directly for every other method.
    const compression =
        request.method === 'POST'
            ? (
                  request.query?.get('compression') ||
                  form?.get('compression') ||
                  request.contentEncoding ||
                  ''
              ).toLowerCase()
            : (request.contentEncoding ?? '').toLowerCase()

    const payload: Buffer | string | null = isForm ? (form?.get('data') ?? null) : request.body

    return { data: decompress(payload, compression), form }
}

export function decompress(data: Buffer | string | null, compression: string): unknown {
    if (data === null || data.length === 0) {
        return null
    }

    let current: Buffer | string = data

    if (GZIP_COMPRESSIONS.has(compression)) {
        if (Buffer.isBuffer(current) ? current.equals(Buffer.from('undefined')) : current === 'undefined') {
            throw new RequestParsingError(
                'data being loaded from the request body for decompression is the literal string "undefined"'
            )
        }
        try {
            current = gunzipSync(Buffer.isBuffer(current) ? current : Buffer.from(current))
        } catch (error) {
            throw new RequestParsingError(`Failed to decompress data. ${String(error)}`)
        }
    }

    if (compression === 'lz64') {
        // Django decompresses this with lzstring. No PostHog mobile SDK sends it — it is a
        // posthog-js path, and web clients do not register devices — so rather than carry a
        // decompressor for traffic that does not exist, this rejects it as an unparseable body.
        throw new RequestParsingError('lz64 compression is not supported.')
    }

    const base64Decoded = tryBase64Decode(current)
    if (base64Decoded !== null) {
        current = base64Decoded
    }

    // `json.loads` on bytes decodes UTF-8 strictly, and the view treats that failure the same way
    // as invalid JSON, so invalid bytes have to fail here rather than become replacement characters.
    const text = Buffer.isBuffer(current) ? decodeUtf8Strict(current) : current
    try {
        if (text === null) {
            throw new SyntaxError('body is not valid UTF-8')
        }
        return parseJsonLikePython(text)
    } catch (error) {
        if (compression !== '') {
            throw new RequestParsingError(`Invalid JSON: ${String(error)}`)
        }
        // A client that gzipped the body without saying so. Django retries as gzip before giving up,
        // so a body it accepts this way must not fail here.
        try {
            return decompress(current, 'gzip')
        } catch {
            throw new UnspecifiedCompressionFallbackParsingError(`Invalid JSON: ${String(error)}`)
        }
    }
}

/** Python's `json.loads` reads the bare tokens `NaN`, `Infinity` and `-Infinity`, and this endpoint
 * maps them to null. `JSON.parse` rejects them outright, so a body carrying one would be a device
 * Django registers and this does not.
 *
 * Only reached once strict parsing has failed, so a string whose *contents* are "NaN" is already
 * parsed and never rewritten.
 */
function parseJsonLikePython(text: string): unknown {
    try {
        // oxlint-disable-next-line eslint-js/no-restricted-syntax
        return JSON.parse(text)
    } catch (error) {
        const rewritten = replaceBareConstants(text)
        if (rewritten === null) {
            throw error
        }
        // oxlint-disable-next-line eslint-js/no-restricted-syntax
        return JSON.parse(rewritten)
    }
}

const BARE_CONSTANT = /^(NaN|-?Infinity)/

/** Replaces the non-JSON numeric constants outside string literals, or null when there are none. */
function replaceBareConstants(text: string): string | null {
    let result = ''
    let index = 0
    let inString = false
    let replaced = false

    while (index < text.length) {
        const character = text[index]
        if (inString) {
            if (character === '\\') {
                result += text.slice(index, index + 2)
                index += 2
                continue
            }
            if (character === '"') {
                inString = false
            }
            result += character
            index += 1
            continue
        }
        if (character === '"') {
            inString = true
            result += character
            index += 1
            continue
        }
        const match = BARE_CONSTANT.exec(text.slice(index))
        if (match) {
            result += 'null'
            index += match[0].length
            replaced = true
            continue
        }
        result += character
        index += 1
    }

    return replaced ? result : null
}

const BASE64_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
const BASE64_VALUES = new Map([...BASE64_ALPHABET].map((character, index) => [character, index]))

/** Django tries base64 on every body before parsing it, so a base64 payload it would accept has to
 * decode here too. Returns null when the attempt fails, which is the usual case for plain JSON.
 *
 * Mirrors `posthog.utils.base64_decode`, which encodes to ASCII, URL-decodes, re-pads, and then
 * decodes leniently. Each of those steps can reject a body, and a body Python rejects here is one it
 * goes on to parse unchanged, so the failures matter as much as the successes.
 */
function tryBase64Decode(data: Buffer | string): string | null {
    const raw = Buffer.isBuffer(data) ? data : Buffer.from(data, 'utf8')
    // Python encodes to ASCII first, so anything outside it raises and the attempt is abandoned.
    if (raw.some((byte) => byte > 0x7f)) {
        return null
    }

    let text = raw.toString('latin1')
    const unquoted = percentDecodeToAscii(text)
    if (unquoted === null) {
        return null
    }
    if (raw.subarray(0, 5).toString('latin1') === 'data=') {
        const separator = unquoted.indexOf('=')
        text = separator === -1 ? '' : unquoted.slice(separator + 1)
    } else {
        text = unquoted
    }

    text = text.replace(/ /g, '')
    const padding = text.length % 4
    if (padding) {
        text += '='.repeat(4 - padding)
    }

    const decoded = pythonB64Decode(text)
    if (decoded === null) {
        return null
    }
    return decodeUtf8Strict(decoded)
}

/** `urllib.parse.unquote` followed by `.encode("ascii")`. A percent-escape for a non-ASCII byte, or
 * a malformed one that Python replaces with U+FFFD, both leave a character the ASCII encode rejects,
 * so either abandons the attempt. Returns null in those cases.
 */
function percentDecodeToAscii(text: string): string | null {
    let result = ''
    let index = 0
    while (index < text.length) {
        if (text[index] === '%' && index + 2 < text.length) {
            const hex = text.slice(index + 1, index + 3)
            if (/^[0-9a-fA-F]{2}$/.test(hex)) {
                const byte = parseInt(hex, 16)
                if (byte > 0x7f) {
                    return null
                }
                result += String.fromCharCode(byte)
                index += 3
                continue
            }
            // Python leaves a malformed escape as the literal characters it found.
        }
        result += text[index]
        index += 1
    }
    return result
}

/** CPython's lenient `binascii.a2b_base64`: characters outside the alphabet are skipped, `=` is
 * skipped inline, and only padding that trails the final data character can close a partial quad.
 *
 * Node's own decoder is more forgiving and accepts bodies Python rejects. That is the direction that
 * changes an answer silently: Python leaving the body untouched is what lets a plain JSON body parse
 * as itself, so accepting more here would corrupt the ordinary request.
 */
function pythonB64Decode(text: string): Buffer | null {
    const out: number[] = []
    let quadPosition = 0
    let trailingPads = 0
    let carry = 0

    for (const character of text) {
        if (character === '=') {
            trailingPads += 1
            continue
        }
        const value = BASE64_VALUES.get(character)
        if (value === undefined) {
            continue
        }
        trailingPads = 0
        switch (quadPosition) {
            case 0:
                carry = value
                quadPosition = 1
                break
            case 1:
                out.push(((carry << 2) | (value >> 4)) & 0xff)
                carry = value & 0x0f
                quadPosition = 2
                break
            case 2:
                out.push(((carry << 4) | (value >> 2)) & 0xff)
                carry = value & 0x03
                quadPosition = 3
                break
            default:
                out.push(((carry << 6) | value) & 0xff)
                quadPosition = 0
                break
        }
    }

    if (quadPosition === 0) {
        return Buffer.from(out)
    }
    // One data character past a quad can never be a byte, and a partial quad needs padding behind it.
    if (quadPosition === 1 || quadPosition + trailingPads < 4) {
        return null
    }
    return Buffer.from(out)
}

/** Python decodes with "surrogatepass", which still raises on bytes that are not valid UTF-8, and
 * that exception is what makes the caller keep the original body. Node's default decoder substitutes
 * U+FFFD instead, which would turn an abandoned attempt into a successful one holding mangled text.
 */
function decodeUtf8Strict(buffer: Buffer): string | null {
    try {
        return new TextDecoder('utf-8', { fatal: true }).decode(buffer)
    } catch {
        return null
    }
}

function parseForm(body: Buffer, contentType: string): URLSearchParams | undefined {
    // Only urlencoded. Django also parses multipart here, but no client sends a device registration
    // that way, and a half-built multipart parser would answer differently from Django rather than
    // not at all.
    if (contentType !== 'application/x-www-form-urlencoded') {
        return undefined
    }
    try {
        return new URLSearchParams(body.toString('utf8'))
    } catch {
        return undefined
    }
}
