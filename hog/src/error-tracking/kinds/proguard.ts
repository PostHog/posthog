import { readFileSync } from 'node:fs'

import { HogError } from '@/core/errors'

import { SymbolDataType, writeSymbolData } from '../container'
import { decodeUtf8 } from '../json'

// ProGuard and R8 mapping files. A port of the proguard 5.7.0 crate's `is_valid`, which posthog-cli
// uses to accept or reject a mapping: among the first 50 records, a field or method must follow a
// class. It works on bytes, like the crate, because its quirks are byte-level.

const NEWLINE = (byte: number | undefined): boolean => byte === 13 || byte === 10
const strictUtf8 = new TextDecoder('utf-8', { fatal: true })

class Reject extends Error {}

function isUtf8(bytes: Uint8Array): boolean {
    try {
        strictUtf8.decode(bytes)
        return true
    } catch {
        return false
    }
}

function skipNewlines(bytes: Uint8Array, at: number): number {
    while (at < bytes.length && NEWLINE(bytes[at])) {
        at++
    }
    return at
}

function startsWith(bytes: Uint8Array, at: number, prefix: string): boolean {
    for (let index = 0; index < prefix.length; index++) {
        if (bytes[at + index] !== prefix.charCodeAt(index)) {
            return false
        }
    }
    return true
}

function expect(bytes: Uint8Array, at: number, prefix: string): number {
    if (!startsWith(bytes, at, prefix)) {
        throw new Reject()
    }
    return at + prefix.length
}

// `parse_until`: everything up to the first byte matching `stop`, which must be valid UTF-8.
function until(bytes: Uint8Array, at: number, stop: (byte: number) => boolean): number {
    let end = at
    while (end < bytes.length && !stop(bytes[end]!)) {
        end++
    }
    if (!isUtf8(bytes.subarray(at, end))) {
        throw new Reject()
    }
    return end
}

// `parse_until_no_newline`: like `until`, but stopping at a newline is an error.
function untilNoNewline(bytes: Uint8Array, at: number, stop: (byte: number) => boolean): number {
    const end = until(bytes, at, (byte) => NEWLINE(byte) || stop(byte))
    if (end < bytes.length && NEWLINE(bytes[end])) {
        throw new Reject()
    }
    return end
}

// Latin-1 bytes Rust's `char::is_numeric` accepts: ASCII digits plus ², ³, ¹, ¼, ½ and ¾.
const NUMERIC_BYTES = new Set([0xb2, 0xb3, 0xb9, 0xbc, 0xbd, 0xbe])
const isNumericByte = (byte: number): boolean => (byte >= 48 && byte <= 57) || NUMERIC_BYTES.has(byte)

// `parse_usize`: the numeric run must be valid UTF-8 and parse as a non-empty usize.
function parseNumber(bytes: Uint8Array, at: number): number {
    let end = at
    while (end < bytes.length && isNumericByte(bytes[end]!)) {
        end++
    }
    const slice = bytes.subarray(at, end)
    if (slice.length === 0 || !isUtf8(slice) || !/^\d+$/.test(Buffer.from(slice).toString('latin1'))) {
        throw new Reject()
    }
    if (BigInt(Buffer.from(slice).toString('latin1')) > 0xffffffffffffffffn) {
        throw new Reject()
    }
    return end
}

type RecordKind = 'header' | 'class' | 'member' | 'error'

function headerRecord(bytes: Uint8Array, at: number): number {
    if (bytes[at] === 0x7b) {
        // An R8 JSON header: whether it parses doesn't change `is_valid`, only the line it takes.
        return skipNewlines(
            bytes,
            until(bytes, at, (byte) => NEWLINE(byte))
        )
    }
    let end = until(bytes, at, (byte) => byte === 0x3a || NEWLINE(byte))
    if (bytes[end] === 0x3a) {
        end = until(bytes, end + 1, (byte) => NEWLINE(byte))
    }
    return skipNewlines(bytes, end)
}

function memberRecord(bytes: Uint8Array, at: number): number {
    let index = expect(bytes, at, '    ')
    let hasStart = false
    try {
        index = parseNumber(bytes, index)
        hasStart = true
    } catch {}
    if (hasStart) {
        index = expect(bytes, index, ':')
        index = parseNumber(bytes, index)
        index = expect(bytes, index, ':')
    }
    index = untilNoNewline(bytes, index, (byte) => byte === 0x20)
    index = expect(bytes, index, ' ')
    index = untilNoNewline(bytes, index, (byte) => byte === 0x20 || byte === 0x28)
    let isMethod = false
    if (bytes[index] === 0x28) {
        isMethod = true
        index = untilNoNewline(bytes, index + 1, (byte) => byte === 0x29)
        index = expect(bytes, index, ')')
    }
    if (isMethod && bytes[index] === 0x3a) {
        index = parseNumber(bytes, index + 1)
        if (bytes[index] === 0x3a) {
            index = parseNumber(bytes, index + 1)
        }
    }
    index = expect(bytes, index, ' -> ')
    index = until(bytes, index, (byte) => NEWLINE(byte))
    return skipNewlines(bytes, index)
}

function classRecord(bytes: Uint8Array, at: number): number {
    let index = untilNoNewline(bytes, at, (byte) => byte === 0x20)
    index = expect(bytes, index, ' -> ')
    index = untilNoNewline(bytes, index, (byte) => byte === 0x3a)
    index = expect(bytes, index, ':')
    return skipNewlines(bytes, index)
}

function nextRecord(bytes: Uint8Array, start: number): [RecordKind, number] {
    const at = skipNewlines(bytes, start)
    let trimmed = at
    while (trimmed < bytes.length && [0x20, 0x09, 0x0a, 0x0c, 0x0d].includes(bytes[trimmed]!)) {
        trimmed++
    }
    try {
        if (bytes[trimmed] === 0x23) {
            let afterHash = trimmed + 1
            while (afterHash < bytes.length && [0x20, 0x09, 0x0a, 0x0c, 0x0d].includes(bytes[afterHash]!)) {
                afterHash++
            }
            return ['header', headerRecord(bytes, afterHash)]
        }
        if (startsWith(bytes, at, '    ')) {
            return ['member', memberRecord(bytes, at)]
        }
        return ['class', classRecord(bytes, at)]
    } catch (error) {
        if (!(error instanceof Reject)) {
            throw error
        }
        // A bad record consumes its line, newline included.
        let end = at
        while (end < bytes.length && !NEWLINE(bytes[end])) {
            end++
        }
        return ['error', Math.min(end + 1, bytes.length)]
    }
}

export function isValidProguardMapping(bytes: Uint8Array): boolean {
    let hasClass = false
    let at = 0
    for (let count = 0; count < 50 && at < bytes.length; count++) {
        const [kind, next] = nextRecord(bytes, at)
        at = next
        if (kind === 'class') {
            hasClass = true
        } else if (kind === 'member' && hasClass) {
            return true
        }
    }
    return false
}

// Reads and validates a mapping. The payload is the file's raw bytes: a BOM or CRLF stays, because
// posthog-cli uploads the bytes as they are and hashes them that way.
export function proguardContainer(path: string, displayPath: string): Buffer {
    const bytes = readFileSync(path)
    try {
        decodeUtf8(bytes)
    } catch {
        throw new HogError(
            'invalid_proguard_mapping',
            `${displayPath} isn't valid UTF-8, so it can't be a ProGuard mapping.`
        )
    }
    if (!isValidProguardMapping(bytes)) {
        throw new HogError(
            'invalid_proguard_mapping',
            `${displayPath} is not a valid ProGuard mapping file.`,
            'Pass the mapping.txt that the Android build writes, usually under app/build/outputs/mapping/.'
        )
    }
    return writeSymbolData(SymbolDataType.ProguardMapping, bytes)
}
