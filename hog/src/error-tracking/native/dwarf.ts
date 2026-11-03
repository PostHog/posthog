// Header-only DWARF 2-5 reader: unit headers, abbreviations, the root DIE's attributes
// and line-program headers. Semantics follow gimli 0.32 (the version posthog-cli links).

import { Cursor, DwarfEof, DwarfError, strAt } from './bytes'
import type { SectionReader } from './object'

export const DW_TAG_compile_unit = 0x11
export const DW_AT_name = 0x03
export const DW_AT_stmt_list = 0x10
export const DW_AT_low_pc = 0x11
export const DW_AT_language = 0x13
export const DW_AT_comp_dir = 0x1b
export const DW_AT_ranges = 0x55
export const DW_AT_str_offsets_base = 0x72
export const DW_AT_addr_base = 0x73
export const DW_AT_GNU_addr_base = 0x2133
export const DW_LANG_Go = 0x16

const F = {
    addr: 0x01,
    block2: 0x03,
    block4: 0x04,
    data2: 0x05,
    data4: 0x06,
    data8: 0x07,
    string: 0x08,
    block: 0x09,
    block1: 0x0a,
    data1: 0x0b,
    flag: 0x0c,
    sdata: 0x0d,
    strp: 0x0e,
    udata: 0x0f,
    ref_addr: 0x10,
    ref1: 0x11,
    ref2: 0x12,
    ref4: 0x13,
    ref8: 0x14,
    ref_udata: 0x15,
    indirect: 0x16,
    sec_offset: 0x17,
    exprloc: 0x18,
    flag_present: 0x19,
    strx: 0x1a,
    addrx: 0x1b,
    ref_sup4: 0x1c,
    strp_sup: 0x1d,
    data16: 0x1e,
    line_strp: 0x1f,
    ref_sig8: 0x20,
    implicit_const: 0x21,
    loclistx: 0x22,
    rnglistx: 0x23,
    ref_sup8: 0x24,
    strx1: 0x25,
    strx2: 0x26,
    strx3: 0x27,
    strx4: 0x28,
    addrx1: 0x29,
    addrx2: 0x2a,
    addrx3: 0x2b,
    addrx4: 0x2c,
    GNU_addr_index: 0x1f01,
    GNU_str_index: 0x1f02,
    GNU_ref_alt: 0x1f20,
    GNU_strp_alt: 0x1f21,
} as const

// Attributes whose DW_FORM_data4/data8 is a section offset (gimli `allow_section_offset`).
const SECTION_OFFSET_ATTRS = new Set([0x02, 0x10, 0x19, 0x2a, 0x2c, 0x40, 0x43, 0x79, 0x46, 0x48, 0x4a, 0x4d, 0x55])
const DW_AT_data_member_location = 0x38

export type AttrValue =
    | { k: 'addr'; v: number }
    | { k: 'data'; v: number } // data1/2/4/8 and udata
    | { k: 'sdata'; v: number }
    | { k: 'secoff'; v: number }
    | { k: 'string'; v: Uint8Array }
    | { k: 'strp'; v: number }
    | { k: 'line_strp'; v: number }
    | { k: 'strx'; v: number }
    | { k: 'addrx'; v: number }
    | { k: 'block'; v: Uint8Array }
    | { k: 'other' }

export interface Attr {
    name: number
    value: AttrValue
}

/** gimli `AttributeValue::udata_value`. */
export function udataValue(v: AttrValue): number | null {
    if (v.k === 'data') {
        return v.v
    }
    if (v.k === 'sdata') {
        return v.v < 0 ? null : v.v
    }
    return null
}

export interface Sections {
    info: SectionReader
    abbrev: Uint8Array
    str: Uint8Array
    lineStr: Uint8Array
    strOffsets: Uint8Array
    addr: Uint8Array
    line: SectionReader
    le: boolean
}

export interface UnitHeader {
    offset: number
    is64: boolean
    version: number
    unitType: number
    addressSize: number
    abbrevOffset: number
    entries: Cursor
    /** Absolute section range of the DIE bytes, used to re-read when the window was too small. */
    entriesStart: number
    entriesEnd: number
    windowed: boolean
}

// Bytes read per unit up front: enough for the header and a root DIE in practice.
const UNIT_WINDOW = 4096

/**
 * gimli `DebugInfoUnitHeadersIter`. Returns the headers parsed before the first error,
 * and that error (symbolic fails the whole session on it, the CLI's pass 1 stops there).
 */
export function unitHeaders(s: Sections): { headers: UnitHeader[]; error: Error | null } {
    const headers: UnitHeader[] = []
    let offset = 0
    try {
        while (offset < s.info.size) {
            // Read only a window per unit: the root DIE sits right after the header.
            const pre = new Cursor(s.info.read(offset, 12), s.le)
            const [length, is64] = pre.initialLength()
            const lenSize = pre.pos
            if (offset + lenSize + length > s.info.size) {
                throw new DwarfEof()
            }
            const take = Math.min(length, UNIT_WINDOW)
            const rest = new Cursor(s.info.read(offset + lenSize, take), s.le)
            const windowed = take < length
            const version = rest.u16()
            let unitType = 1
            let addressSize: number
            let abbrevOffset: number
            if (version >= 2 && version <= 4) {
                abbrevOffset = rest.offset(is64)
                addressSize = rest.addressSize()
            } else if (version === 5) {
                unitType = rest.u8()
                addressSize = rest.addressSize()
                abbrevOffset = rest.offset(is64)
                switch (unitType) {
                    case 1: // compile
                    case 3: // partial
                        break
                    case 2: // type
                    case 6: // split_type
                        rest.u64() // type signature
                        rest.offset(is64) // type offset
                        break
                    case 4: // skeleton
                    case 5: // split_compile
                        rest.u64() // dwo_id
                        break
                    default:
                        throw new DwarfError(`unsupported unit type ${unitType}`)
                }
            } else {
                throw new DwarfError(`unknown DWARF version ${version}`)
            }
            const entriesStart = offset + lenSize + rest.pos
            const entriesEnd = offset + lenSize + length
            headers.push({
                offset,
                is64,
                version,
                unitType,
                addressSize,
                abbrevOffset,
                entries: rest,
                entriesStart,
                entriesEnd,
                windowed,
            })
            offset = entriesEnd
        }
    } catch (e) {
        return { headers, error: e as Error }
    }
    return { headers, error: null }
}

export interface AttrSpec {
    name: number
    form: number
    implicit: number | null
}
export interface Abbrev {
    tag: number
    hasChildren: boolean
    specs: AttrSpec[]
}
export type AbbrevTable = Map<number, Abbrev>

/** gimli `Abbreviations::parse`, including its error cases. */
export function parseAbbrevs(section: Uint8Array, offset: number, le: boolean): AbbrevTable {
    const c = new Cursor(section, le)
    c.skip(offset)
    const table: AbbrevTable = new Map()
    for (;;) {
        if (c.isEmpty()) {
            break
        }
        const code = c.uleb()
        if (code === 0) {
            break
        }
        const tag = c.uleb16()
        if (tag === 0) {
            throw new DwarfError('abbreviation tag zero')
        }
        const hc = c.u8()
        if (hc > 1) {
            throw new DwarfError('bad has_children')
        }
        const specs: AttrSpec[] = []
        for (;;) {
            const name = c.uleb16()
            const form = c.uleb16()
            if (name === 0) {
                if (form !== 0) {
                    throw new DwarfError('expected zero')
                }
                break
            }
            if (form === 0) {
                throw new DwarfError('attribute form zero')
            }
            const implicit = form === F.implicit_const ? c.sleb() : null
            specs.push({ name, form, implicit })
        }
        if (table.has(code)) {
            throw new DwarfError('duplicate abbreviation code')
        }
        table.set(code, { tag, hasChildren: hc === 1, specs })
    }
    return table
}

export class AbbrevCache {
    private map = new Map<number, AbbrevTable | Error>()
    constructor(private s: Sections) {}
    get(offset: number): AbbrevTable {
        let t = this.map.get(offset)
        if (t === undefined) {
            try {
                t = parseAbbrevs(this.s.abbrev, offset, this.s.le)
            } catch (e) {
                t = e as Error
            }
            this.map.set(offset, t)
        }
        if (t instanceof Error) {
            throw t
        }
        return t
    }
}

export interface RootDie {
    tag: number
    attrs: Attr[]
    /** Error hit while parsing attributes; `attrs` holds the ones parsed before it. */
    attrError: Error | null
}

/**
 * gimli `EntriesCursor::next_dfs` on a fresh cursor: skips null entries and returns the
 * first real entry, or null when the unit has none (`MissingUnitDie`).
 * Throws on an unknown abbreviation code or a truncated code.
 */
export function readRootDie(h: UnitHeader, abbrevs: AbbrevTable, info?: SectionReader): RootDie | null {
    const die = readRootDieIn(new Cursor(h.entries.buf, h.entries.le, h.entries.pos, h.entries.end), h, abbrevs)
    const truncated = die === null || die.attrError instanceof DwarfEof
    if (h.windowed && truncated && info) {
        // The window ended inside the root DIE: read the whole unit and parse again.
        const full = info.read(h.entriesStart, h.entriesEnd - h.entriesStart)
        return readRootDieIn(new Cursor(full, h.entries.le), h, abbrevs)
    }
    return die
}

function readRootDieIn(c: Cursor, h: UnitHeader, abbrevs: AbbrevTable): RootDie | null {
    for (;;) {
        if (c.isEmpty()) {
            return null
        }
        const code = c.uleb()
        if (code === 0) {
            continue
        }
        const ab = abbrevs.get(code)
        if (!ab) {
            throw new DwarfError('unknown abbreviation')
        }
        const attrs: Attr[] = []
        let attrError: Error | null = null
        try {
            for (const spec of ab.specs) {
                attrs.push({ name: spec.name, value: parseAttr(c, h, spec) })
            }
        } catch (e) {
            attrError = e as Error
        }
        return { tag: ab.tag, attrs, attrError }
    }
}

/** gimli `parse_attribute` (unit.rs), with gimli's `Attribute::value` normalisation for the attributes we read. */
function parseAttr(c: Cursor, h: UnitHeader, spec: AttrSpec): AttrValue {
    let form = spec.form
    for (;;) {
        switch (form) {
            case F.indirect:
                form = c.uleb16()
                continue
            case F.addr:
                return { k: 'addr', v: c.uint(h.addressSize) }
            case F.block1:
                return { k: 'block', v: c.split(c.u8()).buf }
            case F.block2:
                return { k: 'block', v: c.split(c.u16()).buf }
            case F.block4:
                return { k: 'block', v: c.split(c.u32()).buf }
            case F.block:
            case F.exprloc:
                c.split(c.uleb())
                return { k: 'other' }
            case F.data1:
                return { k: 'data', v: c.u8() }
            case F.data2:
                return { k: 'data', v: c.u16() }
            case F.data4:
                if (!h.is64 && allowSectionOffset(spec.name, h.version)) {
                    return { k: 'secoff', v: c.u32() }
                }
                return { k: 'data', v: c.u32() }
            case F.data8:
                if (h.is64 && allowSectionOffset(spec.name, h.version)) {
                    return { k: 'secoff', v: c.u64() }
                }
                return { k: 'data', v: c.u64() }
            case F.data16:
                c.split(16)
                return { k: 'other' }
            case F.udata:
                return { k: 'data', v: c.uleb() }
            case F.sdata:
                return { k: 'sdata', v: c.sleb() }
            case F.flag:
                c.u8()
                return { k: 'other' }
            case F.flag_present:
                return { k: 'other' }
            case F.sec_offset:
                return { k: 'secoff', v: c.offset(h.is64) }
            case F.ref1:
                c.u8()
                return { k: 'other' }
            case F.ref2:
                c.u16()
                return { k: 'other' }
            case F.ref4:
            case F.ref_sup4:
                c.u32()
                return { k: 'other' }
            case F.ref8:
            case F.ref_sig8:
            case F.ref_sup8:
                c.u64()
                return { k: 'other' }
            case F.ref_udata:
            case F.loclistx:
            case F.rnglistx:
                c.uleb()
                return { k: 'other' }
            case F.ref_addr:
                // DWARF 2 sized DW_FORM_ref_addr like an address.
                if (h.version === 2) {
                    c.uint(h.addressSize)
                } else {
                    c.offset(h.is64)
                }
                return { k: 'other' }
            case F.GNU_ref_alt:
            case F.strp_sup:
            case F.GNU_strp_alt:
                c.offset(h.is64)
                return { k: 'other' }
            case F.string:
                return { k: 'string', v: c.cstr() }
            case F.strp:
                return { k: 'strp', v: c.offset(h.is64) }
            case F.line_strp:
                return { k: 'line_strp', v: c.offset(h.is64) }
            case F.implicit_const:
                if (spec.implicit === null) {
                    throw new DwarfError('invalid implicit const')
                }
                return { k: 'sdata', v: spec.implicit }
            case F.strx:
            case F.GNU_str_index:
                return { k: 'strx', v: c.uleb() }
            case F.strx1:
                return { k: 'strx', v: c.u8() }
            case F.strx2:
                return { k: 'strx', v: c.u16() }
            case F.strx3:
                return { k: 'strx', v: c.uint(3) }
            case F.strx4:
                return { k: 'strx', v: c.u32() }
            case F.addrx:
            case F.GNU_addr_index:
                return { k: 'addrx', v: c.uleb() }
            case F.addrx1:
                return { k: 'addrx', v: c.u8() }
            case F.addrx2:
                return { k: 'addrx', v: c.u16() }
            case F.addrx3:
                return { k: 'addrx', v: c.uint(3) }
            case F.addrx4:
                return { k: 'addrx', v: c.u32() }
            default:
                throw new DwarfError(`unknown form 0x${form.toString(16)}`)
        }
    }
}

function allowSectionOffset(name: number, version: number): boolean {
    return SECTION_OFFSET_ATTRS.has(name) || (name === DW_AT_data_member_location && (version === 2 || version === 3))
}

/** gimli `DebuggingInformationEntry::attr_value`: first match, error if parsing failed before it. */
export function firstAttr(die: RootDie, name: number): AttrValue | null {
    for (const a of die.attrs) {
        if (a.name === name) {
            return a.value
        }
    }
    if (die.attrError) {
        throw die.attrError
    }
    return null
}

export interface StrCtx {
    s: Sections
    is64: boolean
    strOffsetsBase: number
    /** The CLI's pass 1 builds a gimli::Dwarf with an empty .debug_str_offsets. */
    noStrOffsets?: boolean
}

/** gimli `Dwarf::attr_string(..).ok()`: the bytes of any string form, or null. */
export function attrString(ctx: StrCtx, v: AttrValue): Uint8Array | null {
    switch (v.k) {
        case 'string':
            return v.v
        case 'strp':
            return strAt(ctx.s.str, v.v)
        case 'line_strp':
            return strAt(ctx.s.lineStr, v.v)
        case 'strx': {
            if (ctx.noStrOffsets) {
                return null
            }
            const size = ctx.is64 ? 8 : 4
            const at = ctx.strOffsetsBase + v.v * size
            if (at + size > ctx.s.strOffsets.length) {
                return null
            }
            const off = new Cursor(ctx.s.strOffsets, ctx.s.le, at).offset(ctx.is64)
            return strAt(ctx.s.str, off)
        }
        default:
            return null
    }
}

export interface LineFile {
    path: AttrValue
    dirIndex: number
}
export interface LineHeader {
    version: number
    compDir: Uint8Array | null
    includeDirs: AttrValue[]
    files: LineFile[]
}

/** gimli `LineProgramHeader::parse`; throws on the same malformations. */
export function parseLineHeader(
    s: Sections,
    offset: number,
    unitAddressSize: number,
    compDir: Uint8Array | null
): LineHeader {
    if (offset > s.line.size) {
        throw new DwarfEof()
    }
    const pre = new Cursor(s.line.read(offset, 32), s.le)
    const [unitLength, is64] = pre.initialLength()
    const lenSize = pre.pos
    if (offset + lenSize + unitLength > s.line.size) {
        throw new DwarfEof()
    }
    // Read the header only, never the line-number program that follows it.
    const v = pre.remaining >= 2 ? pre.u16() : 0
    const fixed = 2 + (v >= 5 ? 2 : 0) + (is64 ? 8 : 4)
    let preHeaderLength = 0
    if (pre.remaining >= fixed - 2) {
        if (v >= 5) {
            pre.skip(2)
        }
        preHeaderLength = pre.offset(is64)
    }
    // Unit lengths come from the file, so cap the read at the unit's end.
    const take = Math.min(unitLength, fixed + preHeaderLength)
    const rest = new Cursor(s.line.read(offset + lenSize, take), s.le)
    const version = rest.u16()
    if (version < 2 || version > 5) {
        throw new DwarfError(`unknown line program version ${version}`)
    }
    let addressSize = unitAddressSize
    if (version >= 5) {
        addressSize = rest.addressSize()
        if (rest.u8() !== 0) {
            throw new DwarfError('unsupported segment size')
        }
    }
    const headerLength = rest.offset(is64)
    const hdr = rest.split(headerLength)
    const minInstLength = hdr.u8()
    if (minInstLength === 0) {
        throw new DwarfError('minimum instruction length zero')
    }
    const maxOps = version >= 4 ? hdr.u8() : 1
    if (maxOps === 0) {
        throw new DwarfError('maximum operations per instruction zero')
    }
    hdr.u8() // default_is_stmt
    hdr.i8() // line_base
    const lineRange = hdr.u8()
    if (lineRange === 0) {
        throw new DwarfError('line range zero')
    }
    const opcodeBase = hdr.u8()
    if (opcodeBase === 0) {
        throw new DwarfError('opcode base zero')
    }
    const opcodeLengths = hdr.split(opcodeBase - 1)

    const enc = { is64, version, addressSize }
    const includeDirs: AttrValue[] = []
    const files: LineFile[] = []
    if (version <= 4) {
        for (;;) {
            const d = hdr.cstr()
            if (d.length === 0) {
                break
            }
            includeDirs.push({ k: 'string', v: d })
        }
        for (;;) {
            const p = hdr.cstr()
            if (p.length === 0) {
                break
            }
            const dirIndex = hdr.uleb()
            hdr.uleb() // mtime
            hdr.uleb() // length
            files.push({ path: { k: 'string', v: p }, dirIndex })
        }
        const programStart = offset + lenSize + fixed + headerLength
        const program = new Cursor(s.line.read(programStart, unitLength - fixed - headerLength), s.le)
        const params = { minInstLength, maxOps, lineRange, opcodeBase, opcodeLengths, addressSize }
        files.push(...definedFiles(program, params))
        return { version, compDir, includeDirs, files }
    }
    const dirFormat = entryFormat(hdr)
    const dirCount = hdr.uleb()
    for (let i = 0; i < dirCount; i++) {
        let path: AttrValue | null = null
        for (const f of dirFormat) {
            const v = lineAttr(hdr, enc, f.form)
            if (f.type === 1) {
                path = v
            }
        }
        includeDirs.push(path!)
    }
    const fileFormat = entryFormat(hdr)
    const fileCount = hdr.uleb()
    for (let i = 0; i < fileCount; i++) {
        let path: AttrValue | null = null
        let dirIndex = 0
        for (const f of fileFormat) {
            const v = lineAttr(hdr, enc, f.form)
            if (f.type === 1) {
                path = v
            } else if (f.type === 2) {
                dirIndex = udataValue(v) ?? dirIndex
            }
        }
        files.push({ path: path!, dirIndex })
    }
    // DWARF 5 has no implicit compilation directory; index 0 is an explicit entry.
    return { version, compDir: null, includeDirs, files }
}

interface LineProgramParams {
    minInstLength: number
    maxOps: number
    lineRange: number
    opcodeBase: number
    opcodeLengths: Cursor
    addressSize: number
}

const U64_MAX = (1n << 64n) - 1n

/** gimli `leb128::read::unsigned`, exact to 64 bits. */
function uleb64(c: Cursor): bigint {
    let result = 0n
    let shift = 0n
    for (;;) {
        const byte = c.u8()
        if (shift === 63n && byte !== 0x00 && byte !== 0x01) {
            throw new DwarfError('bad unsigned LEB128')
        }
        result |= BigInt(byte & 0x7f) << shift
        if ((byte & 0x80) === 0) {
            return result & U64_MAX
        }
        shift += 7n
    }
}

function uintBig(c: Cursor, size: number): bigint {
    const bytes = c.split(size)
    let value = 0n
    for (let i = 0; i < size; i++) {
        value = (value << 8n) | BigInt(bytes.buf[bytes.pos + (c.le ? size - 1 - i : i)]!)
    }
    return value
}

/** gimli `leb128::read::signed`. Only its errors matter here, so it returns nothing. */
function skipSleb64(c: Cursor): void {
    let shift = 0
    for (;;) {
        const byte = c.u8()
        if (shift === 63 && byte !== 0x00 && byte !== 0x7f) {
            throw new DwarfError('bad signed LEB128')
        }
        shift += 7
        if ((byte & 0x80) === 0) {
            return
        }
    }
}

/**
 * The files `DW_LNE_define_file` adds while the program runs. symbolic runs every line program
 * (`DwarfLineProgram::prepare`) until its end or its first error, and gimli appends each defined
 * file to the header's list. Address arithmetic can raise that error, so it is tracked exactly.
 */
function definedFiles(c: Cursor, p: LineProgramParams): LineFile[] {
    const files: LineFile[] = []
    const ones = p.addressSize === 8 ? U64_MAX : (1n << BigInt(8 * p.addressSize)) - 1n
    const minTombstone = (ones - 1n) & ones
    let address = 0n
    let opIndex = 0n
    let tombstone = false
    const addSized = (length: bigint): void => {
        const sum = address + length
        if (sum > U64_MAX || (sum & ~ones) !== 0n) {
            throw new DwarfError('address overflow')
        }
        address = sum
    }
    const advance = (operationAdvance: bigint): void => {
        if (tombstone) {
            return
        }
        const minInst = BigInt(p.minInstLength)
        const maxOps = BigInt(p.maxOps)
        let addressAdvance: bigint
        if (maxOps === 1n) {
            opIndex = 0n
            addressAdvance = (minInst * operationAdvance) & U64_MAX
        } else {
            const withAdvance = (opIndex + operationAdvance) & U64_MAX
            opIndex = withAdvance % maxOps
            addressAdvance = (minInst * (withAdvance / maxOps)) & U64_MAX
        }
        addSized(addressAdvance)
    }
    try {
        while (!c.isEmpty()) {
            const opcode = c.u8()
            let endSequence = false
            if (opcode === 0) {
                const length = uleb64(c)
                if (length > BigInt(c.remaining)) {
                    throw new DwarfEof()
                }
                const rest = c.split(Number(length))
                const extended = rest.u8()
                if (extended === 0x01) {
                    endSequence = true
                } else if (extended === 0x02) {
                    if (p.addressSize !== 1 && p.addressSize !== 2 && p.addressSize !== 4 && p.addressSize !== 8) {
                        throw new DwarfError('unsupported address size')
                    }
                    const value = uintBig(rest, p.addressSize)
                    tombstone = value < address || value >= minTombstone
                    if (!tombstone) {
                        address = value
                        opIndex = 0n
                    }
                } else if (extended === 0x03) {
                    const path = rest.cstr()
                    const dirIndex = uleb64(rest)
                    uleb64(rest) // mtime
                    uleb64(rest) // length
                    files.push({ path: { k: 'string', v: path }, dirIndex: Number(dirIndex) })
                } else if (extended === 0x04) {
                    uleb64(rest)
                }
            } else if (opcode >= p.opcodeBase) {
                const adjusted = BigInt(opcode - p.opcodeBase)
                advance(adjusted / BigInt(p.lineRange))
            } else if (opcode === 0x02) {
                advance(uleb64(c))
            } else if (opcode === 0x03) {
                skipSleb64(c)
            } else if (opcode === 0x04 || opcode === 0x05 || opcode === 0x0c) {
                uleb64(c)
            } else if (opcode === 0x08) {
                advance(BigInt(255 - p.opcodeBase) / BigInt(p.lineRange))
            } else if (opcode === 0x09) {
                const operand = BigInt(c.u16())
                if (!tombstone) {
                    addSized(operand)
                    opIndex = 0n
                }
            } else if (opcode > 0x0c) {
                const args = p.opcodeLengths.buf[p.opcodeLengths.pos + opcode - 1]!
                for (let i = 0; i < args; i++) {
                    uleb64(c)
                }
            }
            if (endSequence) {
                address = 0n
                opIndex = 0n
                tombstone = false
            }
        }
    } catch (error) {
        if (!(error instanceof DwarfError)) {
            throw error
        }
    }
    return files
}

function entryFormat(c: Cursor): { type: number; form: number }[] {
    const count = c.u8()
    const out: { type: number; form: number }[] = []
    let paths = 0
    for (let i = 0; i < count; i++) {
        const type = Math.min(c.uleb(), 0xffff)
        if (type === 1) {
            paths++
        }
        out.push({ type, form: c.uleb16() })
    }
    if (paths !== 1) {
        throw new DwarfError('missing file entry format path')
    }
    return out
}

/** gimli `parse_attribute` in line.rs: a narrower form set, no section-offset promotion. */
function lineAttr(c: Cursor, enc: { is64: boolean }, form: number): AttrValue {
    switch (form) {
        case F.block1:
            return { k: 'block', v: c.split(c.u8()).buf }
        case F.block2:
            return { k: 'block', v: c.split(c.u16()).buf }
        case F.block4:
            return { k: 'block', v: c.split(c.u32()).buf }
        case F.block:
            return { k: 'block', v: c.split(c.uleb()).buf }
        case F.data1:
            return { k: 'data', v: c.u8() }
        case F.data2:
            return { k: 'data', v: c.u16() }
        case F.data4:
            return { k: 'data', v: c.u32() }
        case F.data8:
            return { k: 'data', v: c.u64() }
        case F.data16:
            c.split(16)
            return { k: 'other' }
        case F.udata:
            return { k: 'data', v: c.uleb() }
        case F.sdata:
            return { k: 'sdata', v: c.sleb() }
        case F.flag:
            c.u8()
            return { k: 'other' }
        case F.sec_offset:
            return { k: 'secoff', v: c.offset(enc.is64) }
        case F.string:
            return { k: 'string', v: c.cstr() }
        case F.strp:
            return { k: 'strp', v: c.offset(enc.is64) }
        case F.strp_sup:
        case F.GNU_strp_alt:
            c.offset(enc.is64)
            return { k: 'other' }
        case F.line_strp:
            return { k: 'line_strp', v: c.offset(enc.is64) }
        case F.strx:
        case F.GNU_str_index:
            return { k: 'strx', v: c.uleb() }
        case F.strx1:
            return { k: 'strx', v: c.u8() }
        case F.strx2:
            return { k: 'strx', v: c.u16() }
        case F.strx3:
            return { k: 'strx', v: c.uint(3) }
        case F.strx4:
            return { k: 'strx', v: c.u32() }
        default:
            throw new DwarfError(`unknown line form 0x${form.toString(16)}`)
    }
}

/** gimli `LineProgramHeader::directory`: DWARF <= 4 index 0 is the unit's comp dir. */
export function fileDirectory(h: LineHeader, index: number): AttrValue | null {
    if (h.version <= 4) {
        if (index === 0) {
            return h.compDir ? { k: 'string', v: h.compDir } : null
        }
        return h.includeDirs[index - 1] ?? null
    }
    return h.includeDirs[index] ?? null
}
