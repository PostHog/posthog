// Builds a relocatable x86-64 ELF with one DWARF 4 compile unit and a hand-written line program,
// for line-program cases no compiler emits. Tests only.

const cstr = (text: string): number[] => [...Buffer.from(text, 'utf8'), 0]

export function uleb(value: bigint | number): number[] {
    let v = BigInt(value)
    const out: number[] = []
    do {
        let byte = Number(v & 0x7fn)
        v >>= 7n
        if (v !== 0n) {
            byte |= 0x80
        }
        out.push(byte)
    } while (v !== 0n)
    return out
}

const u16 = (v: number): number[] => [v & 0xff, (v >> 8) & 0xff]
const u32 = (v: number): number[] => [v & 0xff, (v >> 8) & 0xff, (v >> 16) & 0xff, (v >>> 24) & 0xff]
export const u64 = (v: bigint): number[] => Array.from({ length: 8 }, (_, i) => Number((v >> BigInt(8 * i)) & 0xffn))

export const op = {
    setAddress: (address: bigint): number[] => [0, 9, 0x02, ...u64(address)],
    defineFile: (path: string, dir: number): number[] => {
        const body = [0x03, ...cstr(path), ...uleb(dir), 0, 0]
        return [0, ...uleb(body.length), ...body]
    },
    advancePc: (by: bigint): number[] => [0x02, ...uleb(by)],
    copy: [0x01],
    endSequence: [0, 1, 0x01],
}

export function dwarf4Object(program: number[]): Uint8Array {
    const abbrev = [1, 0x11, 0, 0x03, 0x08, 0x1b, 0x08, 0x10, 0x17, 0x11, 0x01, 0, 0, 0]
    const die = [1, ...cstr('/src/proj/main.c'), ...cstr('/src/proj'), ...u32(0), ...u64(0x1000n)]
    const infoBody = [...u16(4), ...u32(0), 8, ...die]
    const info = [...u32(infoBody.length), ...infoBody]

    // minimum_instruction_length, maximum_operations_per_instruction, default_is_stmt,
    // line_base (-5), line_range, opcode_base, then the standard opcode lengths.
    const encoding = [1, 1, 1, 0xfb, 14, 13]
    const opcodeLengths = [0, 1, 1, 1, 1, 0, 0, 0, 1, 0, 0, 1]
    const file = (name: string, dir: number): number[] => [...cstr(name), dir, 0, 0]
    const header = [
        ...encoding,
        ...opcodeLengths,
        ...cstr('/src/proj/include'),
        0,
        ...file('main.c', 0),
        ...file('util.h', 1),
        0,
    ]
    const lineBody = [...u16(4), ...u32(header.length), ...header, ...program]
    const line = [...u32(lineBody.length), ...lineBody]

    const names = ['', '.debug_abbrev', '.debug_info', '.debug_line', '.shstrtab']
    const shstrtab: number[] = []
    const nameOffsets = names.map((name) => {
        const at = shstrtab.length
        shstrtab.push(...cstr(name))
        return at
    })
    const contents = [abbrev, info, line, shstrtab]
    const body: number[] = []
    const offsets = contents.map((data) => {
        const at = 64 + body.length
        body.push(...data)
        return at
    })
    while ((64 + body.length) % 8 !== 0) {
        body.push(0)
    }
    const sectionHeadersAt = 64 + body.length
    const sectionHeader = (index: number): number[] => {
        if (index === 0) {
            return Array.from({ length: 64 }, () => 0)
        }
        const type = names[index] === '.shstrtab' ? 3 : 1
        return [
            ...u32(nameOffsets[index]!),
            ...u32(type),
            ...u64(0n),
            ...u64(0n),
            ...u64(BigInt(offsets[index - 1]!)),
            ...u64(BigInt(contents[index - 1]!.length)),
            ...u32(0),
            ...u32(0),
            ...u64(1n),
            ...u64(0n),
        ]
    }
    // ELF64, little-endian, version 1.
    const ident = [0x7f, 0x45, 0x4c, 0x46, 2, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    const elfHeader = [
        ...ident,
        ...u16(1), // ET_REL
        ...u16(62), // EM_X86_64
        ...u32(1),
        ...u64(0n),
        ...u64(0n),
        ...u64(BigInt(sectionHeadersAt)),
        ...u32(0),
        ...u16(64),
        ...u16(0),
        ...u16(0),
        ...u16(64),
        ...u16(names.length),
        ...u16(names.length - 1),
    ]
    return Uint8Array.from([...elfHeader, ...body, ...names.flatMap((_, i) => sectionHeader(i))])
}
