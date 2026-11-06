// A bounds-checked cursor over bytes. A read past the end throws DwarfEof, like gimli's
// `Error::UnexpectedEof`, so object and DWARF parsing fail where the Rust crates fail.

export class DwarfError extends Error {}
export class DwarfEof extends DwarfError {
    constructor() {
        super('unexpected end of input')
    }
}

export const textLossy = new TextDecoder('utf-8', { fatal: false, ignoreBOM: true })
const textStrict = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true })

/** Rust `String::from_utf8_lossy`: WHATWG decoding uses the same maximal-subpart replacement. */
export function utf8Lossy(b: Uint8Array): string {
    return textLossy.decode(b)
}

/** Rust `str::from_utf8(..).ok()`. */
export function utf8Strict(b: Uint8Array): string | null {
    try {
        return textStrict.decode(b)
    } catch {
        return null
    }
}

export class Cursor {
    pos: number
    readonly end: number
    private readonly dv: DataView

    constructor(
        readonly buf: Uint8Array,
        readonly le: boolean,
        start = 0,
        end = buf.length
    ) {
        this.pos = start
        this.end = end
        this.dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength)
    }

    get remaining(): number {
        return this.end - this.pos
    }

    isEmpty(): boolean {
        return this.pos >= this.end
    }

    private need(n: number): number {
        if (n < 0 || this.pos + n > this.end) {
            throw new DwarfEof()
        }
        const p = this.pos
        this.pos += n
        return p
    }

    skip(n: number): void {
        this.need(n)
    }

    split(n: number): Cursor {
        const p = this.need(n)
        return new Cursor(this.buf, this.le, p, p + n)
    }

    u8(): number {
        return this.buf[this.need(1)]!
    }
    i8(): number {
        return this.dv.getInt8(this.need(1))
    }
    u16(): number {
        return this.dv.getUint16(this.need(2), this.le)
    }
    u32(): number {
        return this.dv.getUint32(this.need(4), this.le)
    }
    /** u64 as a JS number. Offsets above 2^53 cannot occur in files we can read. */
    u64(): number {
        const p = this.need(8)
        const lo = this.dv.getUint32(this.le ? p : p + 4, this.le)
        const hi = this.dv.getUint32(this.le ? p + 4 : p, this.le)
        return hi * 0x1_0000_0000 + lo
    }
    uint(n: number): number {
        if (n === 1) {
            return this.u8()
        }
        if (n === 2) {
            return this.u16()
        }
        if (n === 4) {
            return this.u32()
        }
        if (n === 8) {
            return this.u64()
        }
        const p = this.need(n)
        let v = 0
        for (let i = 0; i < n; i++) {
            const b = this.buf[this.le ? p + n - 1 - i : p + i]!
            v = v * 256 + b
        }
        return v
    }

    uleb(): number {
        let result = 0
        let mul = 1
        for (;;) {
            const b = this.u8()
            result += (b & 0x7f) * mul
            mul *= 128
            if ((b & 0x80) === 0) {
                return result
            }
            if (mul > 2 ** 70) {
                throw new DwarfError('bad unsigned LEB128')
            }
        }
    }

    /** gimli `read_uleb128_u16`: errors when the value does not fit in 16 bits. */
    uleb16(): number {
        const v = this.uleb()
        if (v > 0xffff) {
            throw new DwarfError('bad unsigned LEB128 (u16)')
        }
        return v
    }

    sleb(): number {
        let result = 0
        let mul = 1
        let b: number
        do {
            b = this.u8()
            result += (b & 0x7f) * mul
            mul *= 128
            if (mul > 2 ** 70) {
                throw new DwarfError('bad signed LEB128')
            }
        } while (b & 0x80)
        if (b & 0x40) {
            result -= mul
        }
        return result
    }

    initialLength(): [number, boolean] {
        const v = this.u32()
        if (v < 0xfffffff0) {
            return [v, false]
        }
        if (v === 0xffffffff) {
            return [this.u64(), true]
        }
        throw new DwarfError('unknown reserved length')
    }

    offset(is64: boolean): number {
        return is64 ? this.u64() : this.u32()
    }

    addressSize(): number {
        const s = this.u8()
        if (s !== 1 && s !== 2 && s !== 4 && s !== 8) {
            throw new DwarfError('unsupported address size')
        }
        return s
    }

    cstr(): Uint8Array {
        const start = this.pos
        const nul = this.buf.indexOf(0, start)
        if (nul < 0 || nul >= this.end) {
            throw new DwarfEof()
        }
        this.pos = nul + 1
        return this.buf.subarray(start, nul)
    }
}

/** Null-terminated string at `offset` in a string section, or null (gimli `get_str(..).ok()`). */
export function strAt(section: Uint8Array, offset: number): Uint8Array | null {
    if (offset < 0 || offset >= section.length) {
        return null
    }
    const nul = section.indexOf(0, offset)
    return nul < 0 ? null : section.subarray(offset, nul)
}
