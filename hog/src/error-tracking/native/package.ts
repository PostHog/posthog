import { closeSync, openSync, readdirSync, readFileSync, readSync, statSync } from 'node:fs'
import { join } from 'node:path'

import { SymbolDataType, writeSymbolData } from '../container'
import { MAX_FILE_SIZE, type SymbolSetUpload } from '../upload'
import { DwarfError } from './bytes'
import { archiveObjects, BufferSource, fatArches, openArchive, type NativeObject } from './object'
import { ZipWriter } from './zip'

export type NativeProblem = 'no_debug_info' | 'no_build_id' | 'missing_uuid' | 'compressed_dwarf' | 'unparseable_slice'

export interface NativeFile {
    path: string
    debugId: string
    format: 'elf' | 'macho'
    data: Uint8Array
}

export type NativeCandidate = { file: NativeFile } | { path: string; problem: NativeProblem }

const ELF_MAGIC = '7f454c46'
const MACHO_MAGICS = ['cffaedfe', 'cefaedfe', 'cafebabe']

// Thin little-endian Mach-O, 32-bit fat, and ELF. Big-endian Mach-O and 64-bit fat files are
// not native files to posthog-cli.
export function nativeFormat(path: string): 'elf' | 'macho' | null {
    let descriptor: number
    try {
        descriptor = openSync(path, 'r')
    } catch {
        return null
    }
    try {
        const magic = Buffer.alloc(4)
        if (readSync(descriptor, magic, 0, 4, 0) !== 4) {
            return null
        }
        const hex = magic.toString('hex')
        return hex === ELF_MAGIC ? 'elf' : MACHO_MAGICS.includes(hex) ? 'macho' : null
    } finally {
        closeSync(descriptor)
    }
}

const isLoadable = (object: NativeObject): boolean =>
    object.kind === 'executable' || object.kind === 'library' || object.kind === 'debug'

// symbolic's view of one file: a fat Mach-O gives one candidate per slice. Relocatable objects
// and other kinds give none. Throws when symbolic can't parse the file.
export function nativeCandidates(path: string): NativeCandidate[] {
    const bytes = readFileSync(path)
    const candidates: NativeCandidate[] = []
    for (const object of archiveObjects(new BufferSource(bytes))) {
        if (object instanceof DwarfError) {
            candidates.push({ path, problem: 'unparseable_slice' })
            continue
        }
        if (!isLoadable(object)) {
            continue
        }
        const data = object.source.read(0, object.source.size)
        if (!object.hasDebugInfo()) {
            const compressed = object.format === 'macho' && Buffer.from(data).includes('__zdebug_')
            candidates.push({ path, problem: compressed ? 'compressed_dwarf' : 'no_debug_info' })
            continue
        }
        const debugId = object.debugId()
        if (!object.hasCodeId() || debugId === null) {
            candidates.push({ path, problem: object.format === 'macho' ? 'missing_uuid' : 'no_build_id' })
            continue
        }
        // Chunk ids are case-sensitive: ELF ids are lowercase and Mach-O ids uppercase, as the SDKs
        // report them.
        candidates.push({
            file: {
                path,
                format: object.format,
                data,
                debugId: object.format === 'macho' ? debugId.toUpperCase() : debugId,
            },
        })
    }
    return candidates
}

export function nativeUpload(file: NativeFile, sources?: (zip: ZipWriter) => void): SymbolSetUpload {
    const zip = new ZipWriter()
    zip.add('dwarf', file.data)
    sources?.(zip)
    const type = file.format === 'macho' ? SymbolDataType.AppleDsym : SymbolDataType.ElfDebugInfo
    return { chunkId: file.debugId, releaseId: null, data: writeSymbolData(type, zip.finish()) }
}

export interface DsymSlice {
    uuid: string
    path: string
    data: Uint8Array
    // The whole file the slice came from, which source collection reads.
    file: Uint8Array
}

// What `dwarfdump --uuid` and `lipo -thin` give posthog-cli: every slice of every binary in the
// bundle, with its uppercase UUID and its own bytes. A thin binary is its whole file.
// Symlinks inside the bundle are followed, as those tools follow them. `include` applies the
// source's ignore globs to members.
export function dsymSlices(bundle: string, include: (path: string) => boolean = () => true): DsymSlice[] {
    if (!statSync(bundle).isDirectory()) {
        throw new Error(`${bundle} is not a directory`)
    }
    const folder = join(bundle, 'Contents', 'Resources', 'DWARF')
    const slices: DsymSlice[] = []
    for (const name of readdirSync(folder).sort()) {
        const path = join(folder, name)
        if (!statSync(path).isFile() || !include(path)) {
            continue
        }
        const bytes = readFileSync(path)
        const source = new BufferSource(bytes)
        const arches = fatArches(source, { fat64: true })
        const parts = arches ? arches.map((arch) => bytes.subarray(arch.offset, arch.offset + arch.size)) : [bytes]
        for (const part of parts) {
            const [object] = openArchive(new BufferSource(part))
            const uuid = object?.debugId()
            if (object?.format === 'macho' && uuid) {
                slices.push({ uuid: uuid.toUpperCase(), path, data: part, file: bytes })
            }
        }
    }
    if (slices.length === 0) {
        throw new Error(`hog found no UUIDs in the dSYM at ${bundle}`)
    }
    return slices
}

export function dsymUpload(slice: DsymSlice, sources?: (zip: ZipWriter) => void): SymbolSetUpload {
    const zip = new ZipWriter()
    zip.add('dwarf', slice.data)
    sources?.(zip)
    return { chunkId: slice.uuid, releaseId: null, data: writeSymbolData(SymbolDataType.AppleDsym, zip.finish()) }
}

// `merge_uploads_prefer_dsym`: dSYM symbol sets that fit go first, so they win over a native file
// with the same id, then native files, then oversized dSYMs. The first set per chunk id stays.
export function mergePreferDsym(
    dsyms: SymbolSetUpload[],
    natives: SymbolSetUpload[],
    onDuplicate: (dropped: SymbolSetUpload) => void
): SymbolSetUpload[] {
    const fits = (upload: SymbolSetUpload): boolean => upload.data.length <= MAX_FILE_SIZE
    const ordered = [...dsyms.filter(fits), ...natives, ...dsyms.filter((upload) => !fits(upload))]
    const seen = new Set<string>()
    return ordered.filter((upload) => {
        if (seen.has(upload.chunkId)) {
            onDuplicate(upload)
            return false
        }
        seen.add(upload.chunkId)
        return true
    })
}

export function dedupeNativeFiles(
    files: NativeFile[],
    onDuplicate: (dropped: NativeFile, kept: NativeFile) => void
): NativeFile[] {
    const kept = new Map<string, NativeFile>()
    for (const file of files) {
        const existing = kept.get(file.debugId)
        if (!existing) {
            kept.set(file.debugId, file)
        } else if (file.data.length > existing.data.length) {
            kept.set(file.debugId, file)
            onDuplicate(existing, file)
        } else {
            onDuplicate(file, existing)
        }
    }
    return [...kept.values()]
}
