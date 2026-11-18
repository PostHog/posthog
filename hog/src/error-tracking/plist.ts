import { readFileSync } from 'node:fs'

import { HogError } from '@/core/errors'
import type { Env } from '@/core/runtime'

import type { ReleaseFields } from './release'

// `--info-plist`: posthog-cli's utils/xcode.rs. The release name, version and build come from an
// iOS Info.plist, XML or binary, where the flags leave them unset.

type PlistValue = string | { other: true } | Map<string, PlistValue>

const OTHER = { other: true } as const

class PlistError extends Error {}

const ENTITIES: Record<string, string> = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'" }

function unescapeXml(text: string): string {
    return text.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (entity, name: string) => {
        if (name.startsWith('#x') || name.startsWith('#X')) {
            return String.fromCodePoint(Number.parseInt(name.slice(2), 16))
        }
        if (name.startsWith('#')) {
            return String.fromCodePoint(Number.parseInt(name.slice(1), 10))
        }
        const value = ENTITIES[name]
        if (value === undefined) {
            throw new PlistError(`unknown entity ${entity}`)
        }
        return value
    })
}

class XmlReader {
    private index = 0

    constructor(private readonly text: string) {}

    // Skips whitespace, comments, the XML declaration and the doctype between elements.
    private skip(): void {
        for (;;) {
            while (/\s/.test(this.text[this.index] ?? '')) {
                this.index++
            }
            const delimiter = this.text.startsWith('<!--', this.index)
                ? '-->'
                : this.text.startsWith('<?', this.index)
                  ? '?>'
                  : this.text.startsWith('<!DOCTYPE', this.index)
                    ? '>'
                    : undefined
            if (delimiter === undefined) {
                return
            }
            const end = this.text.indexOf(delimiter, this.index)
            if (end < 0) {
                throw new PlistError('unterminated markup')
            }
            this.index = end + delimiter.length
        }
    }

    private tag(): { name: string; closing: boolean; empty: boolean } {
        this.skip()
        if (this.text[this.index] !== '<') {
            throw new PlistError(`expected an element at offset ${this.index}`)
        }
        const end = this.text.indexOf('>', this.index)
        if (end < 0) {
            throw new PlistError('unterminated element')
        }
        const inner = this.text.slice(this.index + 1, end)
        this.index = end + 1
        const closing = inner.startsWith('/')
        const empty = inner.endsWith('/')
        const name = inner.replace(/^\//, '').replace(/\/$/, '').trim().split(/\s/)[0] ?? ''
        return { name, closing, empty }
    }

    private content(name: string): string {
        let out = ''
        for (;;) {
            if (this.text.startsWith('<![CDATA[', this.index)) {
                const end = this.text.indexOf(']]>', this.index)
                if (end < 0) {
                    throw new PlistError('unterminated CDATA')
                }
                out += this.text.slice(this.index + 9, end)
                this.index = end + 3
                continue
            }
            if (this.text.startsWith('<!--', this.index)) {
                const end = this.text.indexOf('-->', this.index)
                if (end < 0) {
                    throw new PlistError('unterminated comment')
                }
                this.index = end + 3
                continue
            }
            const next = this.text.indexOf('<', this.index)
            if (next < 0) {
                throw new PlistError(`unterminated <${name}>`)
            }
            out += unescapeXml(this.text.slice(this.index, next))
            this.index = next
            if (!this.text.startsWith('<![CDATA[', next) && !this.text.startsWith('<!--', next)) {
                const close = this.tag()
                if (!close.closing || close.name !== name) {
                    throw new PlistError(`expected </${name}>`)
                }
                return out
            }
        }
    }

    value(open = this.tag()): PlistValue {
        if (open.closing) {
            throw new PlistError(`unexpected </${open.name}>`)
        }
        switch (open.name) {
            case 'string':
                return open.empty ? '' : this.content('string')
            case 'dict': {
                const dict = new Map<string, PlistValue>()
                if (open.empty) {
                    return dict
                }
                for (;;) {
                    const key = this.tag()
                    if (key.closing && key.name === 'dict') {
                        return dict
                    }
                    if (key.name !== 'key') {
                        throw new PlistError(`expected <key>, got <${key.name}>`)
                    }
                    const name = key.empty ? '' : this.content('key')
                    dict.set(name, this.value())
                }
            }
            case 'array': {
                if (open.empty) {
                    return OTHER
                }
                for (;;) {
                    const item = this.tag()
                    if (item.closing && item.name === 'array') {
                        return OTHER
                    }
                    this.value(item)
                }
            }
            case 'true':
            case 'false':
                if (!open.empty) {
                    this.content(open.name)
                }
                return OTHER
            case 'integer':
            case 'real':
            case 'date':
            case 'data':
                if (!open.empty) {
                    this.content(open.name)
                }
                return OTHER
            default:
                throw new PlistError(`unknown element <${open.name}>`)
        }
    }

    document(): PlistValue {
        const first = this.tag()
        if (first.name !== 'plist') {
            return this.value(first)
        }
        const value = this.value()
        const close = this.tag()
        if (!close.closing || close.name !== 'plist') {
            throw new PlistError('expected </plist>')
        }
        return value
    }
}

// The binary format: a trailer of sizes and offsets, an offset table, and tagged objects.
function readBinary(bytes: Buffer): PlistValue {
    if (bytes.length < 40) {
        throw new PlistError('binary plist too short')
    }
    const trailer = bytes.length - 32
    const offsetSize = bytes[trailer + 6]!
    const refSize = bytes[trailer + 7]!
    const count = Number(bytes.readBigUInt64BE(trailer + 8))
    const top = Number(bytes.readBigUInt64BE(trailer + 16))
    const table = Number(bytes.readBigUInt64BE(trailer + 24))
    if (offsetSize < 1 || offsetSize > 8 || refSize < 1 || refSize > 8 || table + count * offsetSize > trailer) {
        throw new PlistError('invalid binary plist trailer')
    }
    const uint = (at: number, size: number): number => {
        if (at + size > bytes.length) {
            throw new PlistError('binary plist offset out of bounds')
        }
        let value = 0
        for (let index = 0; index < size; index++) {
            value = value * 256 + bytes[at + index]!
        }
        return value
    }
    const visiting = new Set<number>()
    const object = (ref: number): PlistValue => {
        if (ref >= count || visiting.has(ref)) {
            throw new PlistError('invalid binary plist reference')
        }
        let at = uint(table + ref * offsetSize, offsetSize)
        const marker = bytes[at]
        if (marker === undefined) {
            throw new PlistError('binary plist offset out of bounds')
        }
        at++
        const kind = marker >> 4
        let length = marker & 0xf
        if (length === 0xf && [0x4, 0x5, 0x6, 0xa, 0xd].includes(kind)) {
            const intMarker = bytes[at]
            if (intMarker === undefined || intMarker >> 4 !== 0x1) {
                throw new PlistError('invalid binary plist length')
            }
            const size = 1 << (intMarker & 0xf)
            length = uint(at + 1, size)
            at += 1 + size
        }
        switch (kind) {
            case 0x5:
                if (at + length > bytes.length) {
                    throw new PlistError('binary plist string out of bounds')
                }
                return bytes.toString('latin1', at, at + length)
            case 0x6: {
                if (at + length * 2 > bytes.length) {
                    throw new PlistError('binary plist string out of bounds')
                }
                const swapped = Buffer.from(bytes.subarray(at, at + length * 2))
                swapped.swap16()
                return swapped.toString('utf16le')
            }
            case 0xd: {
                visiting.add(ref)
                const dict = new Map<string, PlistValue>()
                for (let index = 0; index < length; index++) {
                    const key = object(uint(at + index * refSize, refSize))
                    if (typeof key !== 'string') {
                        throw new PlistError('binary plist dictionary key is not a string')
                    }
                    dict.set(key, object(uint(at + (length + index) * refSize, refSize)))
                }
                visiting.delete(ref)
                return dict
            }
            default:
                return OTHER
        }
    }
    return object(top)
}

export function readInfoPlist(path: string): Map<string, PlistValue> {
    let bytes: Buffer
    try {
        bytes = readFileSync(path)
    } catch {
        throw new HogError('info_plist_not_found', `Info.plist not found at ${path}`, 'Check the --info-plist path.')
    }
    let value: PlistValue
    try {
        value =
            bytes.subarray(0, 8).toString('latin1') === 'bplist00'
                ? readBinary(bytes)
                : new XmlReader(bytes.toString('utf8')).document()
    } catch (error) {
        throw new HogError('invalid_info_plist', `Failed to parse Info.plist: ${(error as Error).message}`)
    }
    if (!(value instanceof Map)) {
        throw new HogError('invalid_info_plist', 'Info.plist is not a dictionary')
    }
    return value
}

// An empty value, or one that still holds an Xcode `$(...)` or `${...}` reference, is unset.
function literal(value: string | undefined): string | undefined {
    return value && !value.includes('$(') && !value.includes('${') ? value : undefined
}

// A value that is exactly one build setting reference, like `$(MARKETING_VERSION)`, reads that
// setting from the environment, as it is during an Xcode build phase.
function resolveSetting(value: string | undefined, env: Env): string | undefined {
    if (value === undefined) {
        return undefined
    }
    const reference = /^\$\(([A-Za-z0-9_]+)\)$/.exec(value) ?? /^\$\{([A-Za-z0-9_]+)\}$/.exec(value)
    return reference ? literal(env[reference[1]!]) : literal(value)
}

export function plistRelease(path: string, env: Env): ReleaseFields {
    const dict = readInfoPlist(path)
    const string = (key: string): string | undefined => {
        const value = dict.get(key)
        return typeof value === 'string' ? value : undefined
    }
    return {
        name: resolveSetting(string('CFBundleIdentifier'), env) ?? literal(env.PRODUCT_BUNDLE_IDENTIFIER),
        version: resolveSetting(string('CFBundleShortVersionString'), env) ?? literal(env.MARKETING_VERSION),
        build: resolveSetting(string('CFBundleVersion'), env) ?? literal(env.CURRENT_PROJECT_VERSION),
    }
}
