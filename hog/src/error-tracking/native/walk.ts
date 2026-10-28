// The posthog-cli source-path walk: `extract_source_paths_from_dwarf_bytes`,
// `filter_source_paths` and `filter_native_source_paths`.

import { DwarfError, utf8Lossy, utf8Strict } from './bytes'
import {
    AbbrevCache,
    type AttrValue,
    DW_AT_addr_base,
    DW_AT_comp_dir,
    DW_AT_GNU_addr_base,
    DW_AT_language,
    DW_AT_low_pc,
    DW_AT_name,
    DW_AT_ranges,
    DW_AT_stmt_list,
    DW_AT_str_offsets_base,
    DW_LANG_Go,
    DW_TAG_compile_unit,
    type Sections,
    type StrCtx,
    attrString,
    fileDirectory,
    firstAttr,
    parseLineHeader,
    readRootDie,
    udataValue,
    unitHeaders,
} from './dwarf'
import { type NativeObject, type Source, bufferReader, openArchive } from './object'
import { cleanPath, joinPath } from './path'

const EXCLUDED_SYNTHETIC_NAMES = [
    '/_AvailabilityInternal',
    '/_Builtin_',
    '/_DarwinFoundation',
    '/CFNetwork',
    '/CoreFoundation',
    '/Darwin',
    '/Dispatch',
    '/Foundation',
    '/MachO',
    '/ObjectiveC',
    '/Security',
    '/XPC',
    '/asl',
    '/os_',
    '/ptrcheck',
    '/ptrauth',
    '<stdin>',
    '<swift-imported-modules>',
]
const EXCLUDED_PREFIXES = ['/usr/', '/Library/Developer/', '/Applications/Xcode', '/System/']
const EXCLUDED_SUBSTRINGS = ['/Xcode.app/', '/SDKs/', '<compiler-generated>', '<built-in>', '/DerivedData/']
const NATIVE_EXCLUDED = ['/.cargo/registry/', '/.cargo/git/', '/rustc/', '/.rustup/toolchains/', '/vendor/']
const GOROOT_WITNESSES = ['runtime/proc.go', 'runtime/malloc.go', 'runtime/mgc.go', 'runtime/runtime2.go']

const EMPTY = new Uint8Array(0)

function loadSections(obj: NativeObject, names: (keyof Omit<Sections, 'le' | 'info' | 'line'>)[]): Sections {
    const map: Record<string, string> = {
        info: 'debug_info',
        abbrev: 'debug_abbrev',
        str: 'debug_str',
        lineStr: 'debug_line_str',
        strOffsets: 'debug_str_offsets',
        addr: 'debug_addr',
        line: 'debug_line',
    }
    const s: Sections = {
        info: obj.window('debug_info') ?? bufferReader(EMPTY),
        abbrev: EMPTY,
        str: EMPTY,
        lineStr: EMPTY,
        strOffsets: EMPTY,
        addr: EMPTY,
        line: obj.window('debug_line') ?? bufferReader(EMPTY),
        le: obj.littleEndian,
    }
    for (const n of names) {
        s[n] = obj.section(map[n]!) ?? EMPTY
    }
    return s
}

interface CuInfo {
    mainFiles: string[]
    hasGo: boolean
}

/** `cu_main_files_from_dwarf`: root DIEs only, strict UTF-8, no .debug_str_offsets. */
function cuMainFiles(obj: NativeObject): CuInfo {
    const s = loadSections(obj, ['abbrev', 'str', 'lineStr'])
    const out: CuInfo = { mainFiles: [], hasGo: false }
    const abbrevs = new AbbrevCache(s)
    const { headers } = unitHeaders(s) // an iteration error just ends the walk
    for (const h of headers) {
        let root
        try {
            root = readRootDie(h, abbrevs.get(h.abbrevOffset), s.info)
        } catch {
            continue
        }
        if (!root || root.tag !== DW_TAG_compile_unit) {
            continue
        }

        const get = (name: number): AttrValue | null => {
            try {
                return firstAttr(root, name)
            } catch {
                return null
            }
        }
        const lang = get(DW_AT_language)
        const langCode = lang ? udataValue(lang) : null
        if (langCode === DW_LANG_Go) {
            out.hasGo = true
            continue
        }
        const ctx: StrCtx = { s, is64: h.is64, strOffsetsBase: 0, noStrOffsets: true }
        const resolve = (v: AttrValue | null): string | null => {
            if (!v || (v.k !== 'string' && v.k !== 'strp' && v.k !== 'line_strp')) {
                return null
            }
            const b = attrString(ctx, v)
            return b ? utf8Strict(b) : null
        }
        const compDir = resolve(get(DW_AT_comp_dir))
        const name = resolve(get(DW_AT_name))

        let path: string
        if (name !== null && name.startsWith('<')) {
            continue
        } else if (compDir !== null && name !== null && !name.startsWith('/')) {
            path = `${compDir.replace(/\/+$/, '')}/${name}`
        } else if (name !== null && name.startsWith('/')) {
            path = name
        } else if (compDir !== null && name === null) {
            path = compDir
        } else {
            continue
        }
        if (path !== '') {
            out.mainFiles.push(path)
        }
    }
    out.mainFiles = out.mainFiles.filter(
        (p) =>
            !EXCLUDED_SYNTHETIC_NAMES.some((x) => p.startsWith(x)) &&
            !EXCLUDED_PREFIXES.some((x) => p.startsWith(x)) &&
            !EXCLUDED_SUBSTRINGS.some((x) => p.includes(x))
    )
    return out
}

/** `longest_common_prefix`: common directory prefix, compared per Unicode scalar value. */
export function longestCommonPrefix(paths: string[]): string | null {
    if (paths.length === 0) {
        return null
    }
    const dirs = paths.map((p) => {
        const i = p.lastIndexOf('/')
        return i >= 0 ? p.slice(0, i + 1) : '/'
    })
    const first = dirs[0]!
    let prefixLen = first.length
    for (const dir of dirs.slice(1)) {
        // Walk both strings by code point; `end` is a UTF-16 index into `first`.
        let i = 0
        let j = 0
        let end = 0
        while (i < first.length && j < dir.length) {
            const a = first.codePointAt(i)!
            const b = dir.codePointAt(j)!
            if (a !== b) {
                break
            }
            i += a > 0xffff ? 2 : 1
            j += b > 0xffff ? 2 : 1
            end = i
        }
        const newLen = first.slice(0, end).lastIndexOf('/') + 1
        prefixLen = Math.min(prefixLen, newLen)
    }
    return prefixLen === 0 ? null : first.slice(0, prefixLen)
}

/**
 * symbolic `DwarfDebugSession::files()` and `FileEntry::abs_path_str()`.
 * Calls `onPath` per file entry; throws where symbolic yields an error.
 */
function sessionFiles(obj: NativeObject, onPath: (p: string) => void): void {
    // symbolic's DwarfSections loads these too; only their lookup can fail (ELF bounds panic).
    for (const n of ['debug_aranges', 'debug_ranges', 'debug_rnglists', 'debug_macinfo', 'debug_macro']) {
        obj.probe(n)
    }
    const s = loadSections(obj, ['abbrev', 'str', 'lineStr', 'strOffsets', 'addr'])
    const { headers, error } = unitHeaders(s)
    if (error) {
        throw error
    } // DwarfInfo::parse collects all headers up front
    const abbrevs = new AbbrevCache(s)
    for (const h of headers) {
        // gimli `Unit::new`
        const root = readRootDie(h, abbrevs.get(h.abbrevOffset), s.info)
        if (!root) {
            continue
        } // MissingUnitDie is skipped silently
        if (root.attrError) {
            throw root.attrError
        }
        let name: AttrValue | null = null
        let compDir: AttrValue | null = null
        let lowPc: AttrValue | null = null
        let stmtList: number | null = null
        let strOffsetsBase = 0
        let addrBase = 0
        for (const a of root.attrs) {
            if (a.name === DW_AT_name) {
                name = a.value
            } else if (a.name === DW_AT_comp_dir) {
                compDir = a.value
            } else if (a.name === DW_AT_low_pc) {
                lowPc = a.value
            } else if (a.name === DW_AT_stmt_list && a.value.k === 'secoff') {
                stmtList = a.value.v
            } else if (a.name === DW_AT_str_offsets_base && a.value.k === 'secoff') {
                strOffsetsBase = a.value.v
            } else if ((a.name === DW_AT_addr_base || a.name === DW_AT_GNU_addr_base) && a.value.k === 'secoff') {
                addrBase = a.value.v
            }
        }
        const ctx: StrCtx = { s, is64: h.is64, strOffsetsBase }
        const nameBytes = name ? attrString(ctx, name) : null
        const compDirBytes = compDir ? attrString(ctx, compDir) : null
        const line = stmtList === null ? null : parseLineHeader(s, stmtList, h.addressSize, compDirBytes)
        void nameBytes // gimli passes the name for the DWARF <= 4 comp_file, which files() never visits
        let lowPcValue = 0
        if (lowPc?.k === 'addr') {
            lowPcValue = lowPc.v
        } else if (lowPc?.k === 'addrx') {
            const at = addrBase + lowPc.v * h.addressSize
            if (at + h.addressSize > s.addr.length) {
                throw new DwarfError('debug_addr index out of range')
            }
            lowPcValue = readAddr(s, at, h.addressSize)
        }

        // symbolic `DwarfUnit::from_unit`: skip units the linker emptied.
        const hasRanges = root.attrs.some((a) => a.name === DW_AT_ranges)
        if (!obj.relocatable && lowPcValue === 0 && !hasRanges) {
            continue
        }
        if (!line) {
            continue
        }

        const compDirStr = compDirBytes ? utf8Lossy(compDirBytes) : ''
        for (const f of line.files) {
            const dirAttr = fileDirectory(line, f.dirIndex)
            const dir = dirAttr ? attrString(ctx, dirAttr) : null
            const fname = attrString(ctx, f.path)
            const joined = joinPath(dir ? utf8Lossy(dir) : '', fname ? utf8Lossy(fname) : '')
            onPath(cleanPath(joinPath(compDirStr, joined)))
        }
    }
}

function readAddr(s: Sections, at: number, size: number): number {
    const dv = new DataView(s.addr.buffer, s.addr.byteOffset + at, size)
    if (size === 1) {
        return dv.getUint8(0)
    }
    if (size === 2) {
        return dv.getUint16(0, s.le)
    }
    if (size === 4) {
        return dv.getUint32(0, s.le)
    }
    const lo = dv.getUint32(s.le ? 0 : 4, s.le)
    const hi = dv.getUint32(s.le ? 4 : 0, s.le)
    return hi * 0x1_0000_0000 + lo
}

/** `is_bundleable_go_source`. */
export function isBundleableGoSource(path: string): boolean {
    const c0 = path.charCodeAt(0)
    const absolute =
        path.startsWith('/') ||
        (path.length > 2 &&
            ((c0 >= 0x41 && c0 <= 0x5a) || (c0 >= 0x61 && c0 <= 0x7a)) &&
            path[1] === ':' &&
            (path[2] === '/' || path[2] === '\\'))
    const normalized = !path.split(/[\\/]/).some((c) => c === '.' || c === '..')
    return absolute && normalized && (path.endsWith('.go') || path.endsWith('.s'))
}

/** `filter_go_toolchain_sources`. */
export function filterGoToolchainSources(paths: string[]): string[] {
    const norm = (p: string): string => p.replaceAll('\\', '/')
    const set = new Set(paths.map(norm))
    const roots: string[] = []
    for (const p of set) {
        const i = p.indexOf('/src/runtime/proc.go')
        if (i < 0) {
            continue
        }
        const root = p.slice(0, i + '/src/'.length)
        if (GOROOT_WITNESSES.every((w) => set.has(root + w))) {
            roots.push(root)
        }
    }
    return paths.filter((p) => {
        const n = norm(p)
        return !n.includes('/pkg/mod/') && !roots.some((r) => n.startsWith(r))
    })
}

/** Rust `String` ordering: byte-wise UTF-8, which equals code-point order. */
function cmpCodePoints(a: string, b: string): number {
    let i = 0
    let j = 0
    while (i < a.length && j < b.length) {
        const x = a.codePointAt(i)!
        const y = b.codePointAt(j)!
        if (x !== y) {
            return x - y
        }
        i += x > 0xffff ? 2 : 1
        j += y > 0xffff ? 2 : 1
    }
    return a.length - i - (b.length - j)
}

/** `extract_source_paths_from_dwarf_bytes`. Throws where the Rust function returns `Err`. */
export function extractSourcePaths(src: Source, opts: { fat64?: boolean } = {}): string[] {
    const paths = new Set<string>()
    let anyGo = false
    for (const obj of openArchive(src, opts)) {
        const cu = cuMainFiles(obj)
        anyGo ||= cu.hasGo
        const prefix = longestCommonPrefix(cu.mainFiles)
        sessionFiles(obj, (abs) => {
            if (abs === '') {
                return
            }
            let keep: boolean
            if (prefix !== null) {
                keep = abs.startsWith(prefix) || (cu.hasGo && isBundleableGoSource(abs))
            } else if (cu.hasGo) {
                keep = isBundleableGoSource(abs)
            } else {
                keep = true
            }
            if (keep) {
                paths.add(abs)
            }
        })
    }
    let out = [...paths].sort(cmpCodePoints)
    if (anyGo) {
        out = filterGoToolchainSources(out)
    }
    return out
}

/** `filter_source_paths` (dSYM upload path). */
export function filterSourcePaths(paths: string[]): string[] {
    return paths.filter((p) => {
        const isGo = p.endsWith('.go') || p.endsWith('.s')
        if (!isGo && EXCLUDED_PREFIXES.some((x) => p.startsWith(x))) {
            return false
        }
        if (EXCLUDED_SUBSTRINGS.some((x) => p.includes(x))) {
            return false
        }
        if (EXCLUDED_SYNTHETIC_NAMES.some((x) => p.startsWith(x))) {
            return false
        }
        return true
    })
}

/** `filter_native_source_paths` (ELF and Mach-O symbol sets). */
export function filterNativeSourcePaths(paths: string[]): string[] {
    return filterSourcePaths(paths).filter((p) => !NATIVE_EXCLUDED.some((x) => p.includes(x)))
}
