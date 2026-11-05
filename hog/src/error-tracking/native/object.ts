import { kMaxLength } from 'node:buffer'
import { closeSync, fstatSync, openSync, readSync } from 'node:fs'
import { constants as zc, inflateRawSync, zstdDecompressSync } from 'node:zlib'

import { Cursor, DwarfError, utf8Strict } from './bytes'

// ELF and Mach-O objects as symbolic-debuginfo 12.17.2 and goblin 0.8.2 read them: the archive
// rules, the object kind, the debug-info check, the identity, and section lookup. Only headers
// and the sections that are asked for are read.

export interface Source {
    readonly size: number
    read(offset: number, length: number): Uint8Array
}

export class BufferSource implements Source {
    readonly size: number

    constructor(private readonly bytes: Uint8Array) {
        this.size = bytes.length
    }

    read(offset: number, length: number): Uint8Array {
        const start = Math.max(0, Math.min(offset, this.size))
        return this.bytes.subarray(start, Math.max(start, Math.min(start + length, this.size)))
    }
}

export class FileSource implements Source {
    private readonly fd: number
    readonly size: number

    constructor(path: string) {
        this.fd = openSync(path, 'r')
        this.size = fstatSync(this.fd).size
    }

    read(offset: number, length: number): Uint8Array {
        const start = Math.max(0, Math.min(offset, this.size))
        const total = Math.max(0, Math.min(length, this.size - start))
        const buffer = new Uint8Array(total)
        let done = 0
        while (done < total) {
            const count = readSync(this.fd, buffer, done, total - done, start + done)
            if (count <= 0) {
                break
            }
            done += count
        }
        return buffer
    }

    close(): void {
        closeSync(this.fd)
    }
}

class SubSource implements Source {
    constructor(
        private readonly inner: Source,
        private readonly base: number,
        readonly size: number
    ) {}

    read(offset: number, length: number): Uint8Array {
        const start = Math.min(offset, this.size)
        return this.inner.read(this.base + start, Math.min(length, this.size - start))
    }
}

export interface SectionReader {
    readonly size: number
    read(offset: number, length: number): Uint8Array
}

export function bufferReader(bytes: Uint8Array): SectionReader {
    return {
        size: bytes.length,
        read: (offset, length) => bytes.subarray(offset, Math.min(bytes.length, offset + length)),
    }
}

function fileReader(source: Source, base: number, size: number): SectionReader {
    return {
        size,
        read: (offset, length) => source.read(base + offset, Math.max(0, Math.min(length, size - offset))),
    }
}

export type ObjectKind = 'none' | 'relocatable' | 'executable' | 'library' | 'dump' | 'debug' | 'other'

export interface NativeObject {
    readonly format: 'macho' | 'elf'
    readonly kind: ObjectKind
    readonly littleEndian: boolean
    readonly relocatable: boolean
    readonly source: Source
    hasDebugInfo(): boolean
    hasCodeId(): boolean
    debugId(): string | null
    section(name: string): Uint8Array | null
    // Looks a section up without reading it, to raise the errors symbolic's eager load raises.
    probe(name: string): void
    window(name: string): SectionReader | null
}

const MH_MAGIC = 0xfeedface
const MH_CIGAM = 0xcefaedfe
const MH_MAGIC_64 = 0xfeedfacf
const MH_CIGAM_64 = 0xcffaedfe
const FAT_MAGIC = 0xcafebabe
const FAT_MAGIC_64 = 0xcafebabf

export interface FatArch {
    cputype: number
    cpusubtype: number
    offset: number
    size: number
}

export function fatArches(source: Source, options: { fat64?: boolean } = {}): FatArch[] | null {
    const head = source.read(0, 8)
    if (head.length < 8) {
        return null
    }
    const view = new DataView(head.buffer, head.byteOffset, head.length)
    const magic = view.getUint32(0, false)
    const is64 = magic === FAT_MAGIC_64 && options.fat64 === true
    if (magic !== FAT_MAGIC && !is64) {
        return null
    }
    const count = view.getUint32(4, false)
    // Java class files share CAFEBABE. symbolic treats 45 or more "arches" as not Mach-O.
    if (count >= 45) {
        return null
    }
    const entry = is64 ? 32 : 20
    const table = new Cursor(source.read(8, count * entry), false)
    const arches: FatArch[] = []
    for (let index = 0; index < count; index++) {
        const cputype = table.u32()
        const cpusubtype = table.u32()
        const offset = is64 ? table.u64() : table.u32()
        const size = is64 ? table.u64() : table.u32()
        table.u32()
        if (is64) {
            table.u32()
        }
        arches.push({ cputype, cpusubtype, offset, size })
    }
    return arches
}

// symbolic `Archive::parse(..).objects()`: throws where symbolic returns an error, and returns
// one object per fat slice.
export function openArchive(source: Source, options: { fat64?: boolean } = {}): NativeObject[] {
    return archiveObjects(source, options).map((object) => {
        if (object instanceof DwarfError) {
            throw object
        }
        return object
    })
}

// Like `openArchive`, but a fat slice that can't be parsed is a `DwarfError` in its place, as
// symbolic's iterator yields it, so the other slices stay usable.
export function archiveObjects(source: Source, options: { fat64?: boolean } = {}): (NativeObject | DwarfError)[] {
    const head = source.read(0, 8)
    if (head.length >= 4 && head[0] === 0x7f && head[1] === 0x45 && head[2] === 0x4c && head[3] === 0x46) {
        return [new ElfObject(source)]
    }
    if (head.length < 4) {
        throw new DwarfError('unsupported object file format')
    }
    const magic = new DataView(head.buffer, head.byteOffset, head.length).getUint32(0, false)
    if (magic === MH_MAGIC || magic === MH_CIGAM || magic === MH_MAGIC_64 || magic === MH_CIGAM_64) {
        return [new MachObject(source)]
    }
    const arches = fatArches(source, options)
    if (arches) {
        return arches.map((arch) => {
            if (arch.offset + arch.size > source.size) {
                return new DwarfError('fat arch out of bounds')
            }
            try {
                return new MachObject(new SubSource(source, arch.offset, arch.size))
            } catch (error) {
                if (error instanceof DwarfError) {
                    return error
                }
                throw error
            }
        })
    }
    throw new DwarfError('unsupported object file format')
}

function formatUuid(bytes: Uint8Array): string | null {
    if (bytes.every((byte) => byte === 0)) {
        return null
    }
    const hex = Buffer.from(bytes).toString('hex')
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20, 32)}`
}

interface MachSection {
    poison?: boolean
    name: string
    offset: number
    size: number
    zerofill: boolean
}

const MACH_KINDS: Record<number, ObjectKind> = {
    0x1: 'relocatable',
    0x2: 'executable',
    0x3: 'library',
    0x4: 'dump',
    0x5: 'executable',
    0x6: 'library',
    0x7: 'executable',
    0x8: 'library',
    0xa: 'debug',
    0xb: 'library',
}

class MachObject implements NativeObject {
    readonly format = 'macho' as const
    readonly kind: ObjectKind
    readonly littleEndian: boolean
    readonly relocatable: boolean
    readonly cputype: number
    readonly cpusubtype: number
    private readonly sections: MachSection[] = []
    private readonly cache = new Map<string, Uint8Array | null>()
    private uuid: string | null = null

    constructor(readonly source: Source) {
        const header = source.read(0, 32)
        if (header.length < 28) {
            throw new DwarfError('truncated Mach-O header')
        }
        const magic = new DataView(header.buffer, header.byteOffset, header.length).getUint32(0, false)
        this.littleEndian = magic === MH_CIGAM || magic === MH_CIGAM_64
        const is64 = magic === MH_MAGIC_64 || magic === MH_CIGAM_64
        const cursor = new Cursor(header, this.littleEndian, 4)
        this.cputype = cursor.u32()
        this.cpusubtype = cursor.u32()
        const filetype = cursor.u32()
        const ncmds = cursor.u32()
        const sizeofcmds = cursor.u32()
        this.kind = MACH_KINDS[filetype] ?? 'other'
        this.relocatable = filetype === 1
        // goblin's non-lossy `MachO::parse` rejects these, and symbolic reports an invalid file.
        const bad = (why: string): never => {
            throw new DwarfError(`invalid MachO file (${why})`)
        }
        if (ncmds > Math.floor(sizeofcmds / 8) || sizeofcmds > source.size) {
            bad('load command count')
        }
        let hasText = false
        let hasMain = false
        // goblin reads each command at the running offset, not bounded by sizeofcmds, and
        // advances by cmdsize whatever its value. A cmdsize below the 8-byte header is the one
        // difference: dyld rejects it, and here it would re-read one command for every ncmds.
        let position = is64 ? 32 : 28
        for (let index = 0; index < ncmds; index++) {
            if (position + 8 > source.size) {
                bad('load command out of bounds')
            }
            const command = new Cursor(source.read(position, 8), this.littleEndian)
            const cmd = command.u32()
            const cmdsize = command.u32()
            if (cmdsize > source.size - position) {
                bad('load command larger than the file')
            }
            if (cmdsize < 8) {
                bad('load command smaller than its header')
            }
            if (cmd === 0x19 || cmd === 0x1) {
                const segment64 = cmd === 0x19
                const segmentSize = segment64 ? 72 : 56
                if (position + segmentSize > source.size) {
                    bad('segment command out of bounds')
                }
                const segment = new Cursor(source.read(position, segmentSize), this.littleEndian, 8)
                const segname = segment.split(16).buf.subarray(segment.pos - 16, segment.pos)
                if (String.fromCharCode(...segname.subarray(0, 7)) === '__TEXT\0') {
                    hasText = true
                }
                segment.skip(segment64 ? 8 : 4)
                segment.skip(segment64 ? 8 : 4)
                const fileoff = segment64 ? segment.u64() : segment.u32()
                const filesize = segment64 ? segment.u64() : segment.u32()
                if (filesize !== 0 && fileoff + filesize > source.size) {
                    bad('segment data out of bounds')
                }
                segment.skip(8)
                const nsects = segment.u32()
                // A section header past the end of the file fails every later section lookup.
                const sectionSize = segment64 ? 80 : 68
                const tableAt = position + segmentSize
                const fit = Math.max(0, Math.min(nsects, Math.floor((source.size - tableAt) / sectionSize)))
                const table = new Cursor(source.read(tableAt, fit * sectionSize), this.littleEndian)
                for (let section = 0; section < fit; section++) {
                    const sectname = table.buf.subarray(table.pos, table.pos + 16)
                    table.skip(32)
                    table.skip(segment64 ? 8 : 4)
                    const size = segment64 ? table.u64() : table.u32()
                    const offset = table.u32()
                    table.skip(12)
                    const flags = table.u32()
                    table.skip(segment64 ? 12 : 8)
                    const nul = sectname.indexOf(0)
                    const type = flags & 0xff
                    this.sections.push({
                        name: utf8Strict(nul < 0 ? sectname : sectname.subarray(0, nul)) ?? '',
                        offset,
                        size,
                        zerofill: type === 0x1 || type === 0xc || type === 0x12,
                    })
                }
                if (fit < nsects) {
                    this.sections.push({ name: '', offset: 0, size: 0, zerofill: false, poison: true })
                }
            } else if (cmd === 0x2) {
                if (position + 24 > source.size) {
                    bad('symtab command out of bounds')
                }
                const symtab = new Cursor(source.read(position + 8, 16), this.littleEndian)
                const symoff = symtab.u32()
                symtab.u32()
                const stroff = symtab.u32()
                if (stroff < symoff || symoff >= source.size) {
                    bad('symbol table offset')
                }
            } else if (cmd === 0x1b && this.uuid === null && cmdsize >= 24) {
                this.uuid = formatUuid(source.read(position + 8, 16))
            } else if (cmd === 0x80000028) {
                hasMain = true
            }
            position += cmdsize
        }
        if (hasMain && !hasText) {
            bad('LC_MAIN without __TEXT')
        }
    }

    hasDebugInfo(): boolean {
        return this.find('debug_info') !== null
    }

    hasCodeId(): boolean {
        return true
    }

    debugId(): string | null {
        return this.uuid
    }

    section(name: string): Uint8Array | null {
        if (!this.cache.has(name)) {
            const reader = this.window(name)
            this.cache.set(name, reader ? reader.read(0, reader.size) : null)
        }
        return this.cache.get(name)!
    }

    probe(): void {}

    window(name: string): SectionReader | null {
        const section = this.find(name)
        if (section === null) {
            return null
        }
        if (section.zerofill || section.offset > this.source.size || section.offset + section.size > this.source.size) {
            return bufferReader(new Uint8Array(0))
        }
        return fileReader(this.source, section.offset, section.size)
    }

    private find(name: string): MachSection | null {
        for (const section of this.sections) {
            if (section.poison) {
                return null
            }
            if (!section.name.startsWith('__')) {
                continue
            }
            // Mach-O section names hold at most 16 bytes: `__debug_str_offs`.
            const short = section.name.slice(2)
            if ((short === 'debug_str_offs' ? 'debug_str_offsets' : short) !== name) {
                continue
            }
            // dsymutil can keep a header but drop its data. symbolic treats that as missing.
            return section.offset === 0 ? null : section
        }
        return null
    }
}

// goblin `Strtab::parse`: every NUL-separated string must be valid UTF-8, else the table is empty.
function parseStrtab(bytes: Uint8Array): { start: number; bytes: Uint8Array }[] {
    const out: { start: number; bytes: Uint8Array }[] = []
    let index = 0
    while (index < bytes.length) {
        let end = bytes.indexOf(0, index)
        if (end < 0) {
            end = bytes.length
        }
        const text = bytes.subarray(index, end)
        if (utf8Strict(text) === null) {
            return []
        }
        out.push({ start: index, bytes: text })
        index = end + 1
    }
    return out
}

interface ElfSection {
    nameOffset: number
    type: number
    flags: number
    offset: number
    size: number
    align: number
}

interface ProgramHeader {
    type: number
    offset: number
    filesz: number
    align: number
}

const ELF_KINDS: Record<number, ObjectKind> = {
    0: 'none',
    1: 'relocatable',
    2: 'executable',
    3: 'library',
    4: 'dump',
    0xfe10: 'executable',
    0xfe18: 'library',
}

const PT_INTERP = 3
const PT_NOTE = 4
const PT_SCE_DYNLIBDATA = 0x61000000
const SHT_NOTE = 7
const SHT_NOBITS = 8
const NT_GNU_BUILD_ID = 3

class ElfObject implements NativeObject {
    readonly format = 'elf' as const
    readonly kind: ObjectKind
    readonly littleEndian: boolean
    readonly relocatable: boolean
    private readonly is64: boolean
    private readonly sections: ElfSection[] = []
    private readonly programs: ProgramHeader[] = []
    private shstrtab: { start: number; bytes: Uint8Array }[] = []
    private readonly cache = new Map<string, Uint8Array | null>()
    private buildId: Uint8Array | null | undefined

    constructor(readonly source: Source) {
        const header = source.read(0, 64)
        const invalid = (): never => {
            throw new DwarfError('ELF header unreadable')
        }
        if (header.length < 52 || (header[4] !== 1 && header[4] !== 2) || (header[5] !== 1 && header[5] !== 2)) {
            invalid()
        }
        this.is64 = header[4] === 2
        if (this.is64 && header.length < 64) {
            invalid()
        }
        this.littleEndian = header[5] === 1
        const cursor = new Cursor(header, this.littleEndian, 16)
        const etype = cursor.u16()
        this.relocatable = etype === 1
        cursor.u16()
        cursor.u32()
        cursor.skip(this.is64 ? 8 : 4)
        const phoff = this.is64 ? cursor.u64() : cursor.u32()
        const shoff = this.is64 ? cursor.u64() : cursor.u32()
        cursor.u32()
        cursor.u16()
        // goblin sizes entries from the ELF class, not from e_phentsize and e_shentsize.
        cursor.u16()
        const phnum = cursor.u16()
        cursor.u16()
        let shnum = cursor.u16()
        const shstrndx = cursor.u16()

        const programSize = this.is64 ? 56 : 32
        if (phnum > Math.floor(source.size / programSize) || (phnum > 0 && phoff + phnum * programSize > source.size)) {
            throw new DwarfError('unable to parse program headers')
        }
        const programTable = source.read(phoff, phnum * programSize)
        for (let index = 0; index < phnum; index++) {
            this.programs.push(this.readPhdr(programTable.subarray(index * programSize, (index + 1) * programSize)))
        }
        const entrySize = this.is64 ? 64 : 40
        if (shoff !== 0) {
            if (shoff + entrySize > source.size) {
                throw new DwarfError('unable to parse section headers')
            }
            const first = this.readShdr(source.read(shoff, entrySize))
            // With more than 0xff00 sections, the real count lives in the null header's sh_size.
            if (shnum === 0) {
                shnum = first.size
            }
            if (shnum > Math.floor(source.size / entrySize) || shoff + shnum * entrySize > source.size) {
                throw new DwarfError('unable to parse section headers')
            }
            const table = source.read(shoff, shnum * entrySize)
            for (let index = 0; index < shnum; index++) {
                this.sections.push(this.readShdr(table.subarray(index * entrySize, (index + 1) * entrySize)))
            }
        }
        // A bad name table only leaves the object without section names (`return_partial_on_err!`).
        // SHN_XINDEX is not followed.
        const names = this.sections[shstrndx]
        if (names && !(names.type !== SHT_NOBITS && names.size !== 0 && names.offset + names.size > source.size)) {
            this.shstrtab = parseStrtab(source.read(names.offset, names.size))
        }
        this.kind = this.classify(etype)
    }

    private classify(etype: number): ObjectKind {
        const kind = ELF_KINDS[etype] ?? 'other'
        // objcopy --only-keep-debug keeps ET_EXEC but drops the interpreter, and keeps ET_DYN
        // but drops `.text`.
        if (kind === 'executable' && this.interpreter() === null) {
            return 'debug'
        }
        if (kind === 'library' && this.find('text') === null) {
            return 'debug'
        }
        return kind
    }

    // goblin keeps the last PT_INTERP with data, as a string without its terminator.
    private interpreter(): string | null {
        let found: string | null = null
        for (const program of this.programs) {
            if (program.type === PT_INTERP && program.filesz !== 0) {
                const end = program.offset + program.filesz - 1
                found =
                    end <= this.source.size ? utf8Strict(this.source.read(program.offset, program.filesz - 1)) : null
            }
        }
        return found
    }

    private readPhdr(bytes: Uint8Array): ProgramHeader {
        const cursor = new Cursor(bytes, this.littleEndian)
        const type = cursor.u32()
        if (this.is64) {
            cursor.u32()
            const offset = cursor.u64()
            cursor.u64()
            cursor.u64()
            const filesz = cursor.u64()
            cursor.u64()
            return { type, offset, filesz, align: cursor.u64() }
        }
        const offset = cursor.u32()
        cursor.u32()
        cursor.u32()
        const filesz = cursor.u32()
        cursor.u32()
        cursor.u32()
        return { type, offset, filesz, align: cursor.u32() }
    }

    private readShdr(bytes: Uint8Array): ElfSection {
        const cursor = new Cursor(bytes, this.littleEndian)
        const nameOffset = cursor.u32()
        const type = cursor.u32()
        const flags = this.is64 ? cursor.u64() : cursor.u32()
        cursor.skip(this.is64 ? 8 : 4)
        const offset = this.is64 ? cursor.u64() : cursor.u32()
        const size = this.is64 ? cursor.u64() : cursor.u32()
        cursor.u32()
        cursor.u32()
        const align = this.is64 ? cursor.u64() : cursor.u32()
        return { nameOffset, type, flags, offset, size, align }
    }

    // goblin `Strtab::get_at`: an exact string start, or a suffix that starts on a char boundary.
    private nameAt(offset: number): string | null {
        const table = this.shstrtab
        let low = 0
        let high = table.length
        while (low < high) {
            const middle = (low + high) >> 1
            if (table[middle]!.start <= offset) {
                low = middle + 1
            } else {
                high = middle
            }
        }
        if (low === 0) {
            return null
        }
        const { start, bytes } = table[low - 1]!
        const relative = offset - start
        if (relative > bytes.length || (relative < bytes.length && (bytes[relative]! & 0xc0) === 0x80)) {
            return null
        }
        return utf8Strict(bytes.subarray(relative))
    }

    // goblin's note iterators: PT_NOTE program headers first, then `.note.gnu.build-id`
    // sections, then a 20-byte PT_SCE_DYNLIBDATA. The first error ends a list.
    private findBuildId(): Uint8Array | null {
        if (this.buildId !== undefined) {
            return this.buildId
        }
        const fromNotes = (regions: { offset: number; size: number; align: number }[]): Uint8Array | null => {
            for (const region of regions) {
                let offset = region.offset
                const end = region.offset + region.size
                while (offset < end) {
                    const note = this.readNote(offset, region.align)
                    if (note === null) {
                        return null
                    }
                    if (note.type === NT_GNU_BUILD_ID) {
                        return note.desc
                    }
                    offset = note.next
                }
            }
            return null
        }
        let found = fromNotes(
            this.programs
                .filter((program) => program.type === PT_NOTE)
                .map((program) => ({ offset: program.offset, size: program.filesz, align: program.align }))
        )
        found ??= fromNotes(
            this.sections
                .filter(
                    (section) => section.type === SHT_NOTE && this.nameAt(section.nameOffset) === '.note.gnu.build-id'
                )
                .map((section) => ({ offset: section.offset, size: section.size, align: section.align }))
        )
        if (found === null) {
            for (const program of this.programs) {
                if (program.type === PT_SCE_DYNLIBDATA && program.filesz >= 20) {
                    found = program.offset + 20 <= this.source.size ? this.source.read(program.offset, 20) : null
                    break
                }
            }
        }
        this.buildId = found
        return found
    }

    private readNote(offset: number, align: number): { type: number; desc: Uint8Array; next: number } | null {
        const alignment = align < 4 ? 4 : align
        if (alignment !== 4 && alignment !== 8) {
            return null
        }
        const pad = (value: number): number =>
            value % alignment === 0 ? value : value + alignment - (value % alignment)
        if (offset + 12 > this.source.size) {
            return null
        }
        const header = new Cursor(this.source.read(offset, 12), this.littleEndian)
        const namesz = header.u32()
        const descsz = header.u32()
        const type = header.u32()
        let position = offset + 12
        const nameLength = Math.max(0, namesz - 1)
        if (position + nameLength > this.source.size || utf8Strict(this.source.read(position, nameLength)) === null) {
            return null
        }
        position = pad(position - offset + nameLength + (namesz > 0 ? 1 : 0)) + offset
        if (position + descsz > this.source.size) {
            return null
        }
        const desc = this.source.read(position, descsz)
        return { type, desc, next: pad(position - offset + descsz) + offset }
    }

    hasDebugInfo(): boolean {
        return this.find('debug_info') !== null
    }

    hasCodeId(): boolean {
        const id = this.findBuildId()
        return id !== null && id.length > 0
    }

    // symbolic `compute_debug_id`: the first 16 bytes of the build id, zero-padded, with the
    // first three UUID fields byte-swapped for little-endian files.
    debugId(): string | null {
        const id = this.findBuildId()
        if (id === null) {
            return null
        }
        const data = new Uint8Array(16)
        data.set(id.subarray(0, 16))
        if (this.littleEndian) {
            data.subarray(0, 4).reverse()
            data.subarray(4, 6).reverse()
            data.subarray(6, 8).reverse()
        }
        return formatUuid(data)
    }

    section(name: string): Uint8Array | null {
        if (!this.cache.has(name)) {
            this.cache.set(name, this.load(name))
        }
        return this.cache.get(name)!
    }

    probe(name: string): void {
        this.find(name)
    }

    window(name: string): SectionReader | null {
        const hit = this.find(name)
        if (!hit) {
            return null
        }
        if (hit.compressed) {
            const data = this.section(name)
            return data ? bufferReader(data) : null
        }
        return fileReader(this.source, hit.section.offset, hit.section.size)
    }

    private load(name: string): Uint8Array | null {
        const hit = this.find(name)
        if (!hit) {
            return null
        }
        const data = this.source.read(hit.section.offset, hit.section.size)
        return hit.compressed ? this.decompress(data) : data
    }

    private find(name: string): { section: ElfSection; compressed: boolean } | null {
        for (const section of this.sections) {
            if (section.type === SHT_NOBITS) {
                continue
            }
            const full = this.nameAt(section.nameOffset)
            if (full === null || section.offset === 0 || full === '') {
                continue
            }
            // `.zdebug_*` is the GNU format from before SHF_COMPRESSED. Otherwise symbolic drops
            // the first character, whatever it is.
            const compressed = full.startsWith('.z') || (section.flags & 0x800) !== 0
            const short = full.startsWith('.z') ? full.slice(2) : full.slice(1)
            if (short !== name) {
                continue
            }
            // symbolic slices without a bounds check here, so posthog-cli panics.
            if (section.offset + section.size > this.source.size) {
                throw new DwarfError('panic: section out of bounds')
            }
            return { section, compressed }
        }
        return null
    }

    // symbolic `ElfObject::decompress_section`. Any failure means the section is missing.
    private decompress(data: Uint8Array): Uint8Array | null {
        let zstd: boolean
        let size: number
        let payload: Uint8Array
        if (data.length >= 4 && data[0] === 0x5a && data[1] === 0x4c && data[2] === 0x49 && data[3] === 0x42) {
            if (data.length < 12) {
                return null
            }
            zstd = false
            size = new Cursor(data, false, 4).u64()
            payload = data.subarray(12)
        } else {
            try {
                const cursor = new Cursor(data, this.littleEndian)
                const type = cursor.u32()
                if (this.is64) {
                    cursor.u32()
                }
                size = this.is64 ? cursor.u64() : cursor.u32()
                if (type !== 1 && type !== 2) {
                    return null
                }
                zstd = type === 2
            } catch {
                return null
            }
            payload = data.subarray(this.is64 ? 24 : 12)
        }
        // Inflating stops at the declared size, so a small crafted section can't fill memory. A
        // stream longer than that is refused, where symbolic keeps the first `size` bytes.
        const maxOutputLength = Math.min(Math.max(size, 1), kMaxLength)
        try {
            if (zstd) {
                return new Uint8Array(zstdDecompressSync(payload, { maxOutputLength }))
            }
            // flate2's `decompress_vec` never reads the adler32 trailer, so validate the zlib
            // header and inflate the raw deflate stream.
            if (payload.length < 2) {
                return null
            }
            const cmf = payload[0]!
            const flg = payload[1]!
            if ((cmf & 0x0f) !== 8 || cmf >> 4 > 7 || (cmf * 256 + flg) % 31 !== 0 || flg & 0x20) {
                return null
            }
            return new Uint8Array(
                inflateRawSync(payload.subarray(2), { finishFlush: zc.Z_SYNC_FLUSH, maxOutputLength })
            )
        } catch {
            return null
        }
    }
}

export function isMachObject(object: NativeObject): object is NativeObject & { cputype: number; cpusubtype: number } {
    return object.format === 'macho'
}
