import { closeSync, constants, fstatSync, lstatSync, openSync, readSync, realpathSync } from 'node:fs'

import { compareUtf8, writeString } from '../json'
import { BufferSource, type Source } from './object'
import { extractSourcePaths, filterNativeSourcePaths, filterSourcePaths } from './walk'
import type { ZipWriter } from './zip'

// `--include-source`: the source files the DWARF names go into the zip under `__source/`, with a
// manifest from DWARF path to zip path. posthog-cli's dsym/source_bundle.rs.

const MAX_SOURCE_FILE_BYTES = 64 * 1024 * 1024

export interface SourceBundle {
    manifest: Map<string, string>
    // Zip path to bytes. A later file with the same zip path replaces the earlier bytes.
    contents: Map<string, Uint8Array>
}

// Rust's `Path::file_name`: the last normal component, ignoring trailing separators and `.`
// components, and none for `..`, `/` or an empty path. Windows also splits on `\`.
export function fileName(path: string, platform: NodeJS.Platform = process.platform): string | null {
    const parts = path.split(platform === 'win32' ? /[\\/]/ : '/').filter((part) => part !== '' && part !== '.')
    const last = parts[parts.length - 1]
    return last === undefined || last === '..' ? null : last
}

// `build_zip_relative_paths`: start from file names, then give every name shared by several files
// one more parent directory per round, for at most 10 rounds.
export function zipRelativePaths(paths: string[]): string[] {
    const result = paths.map((path) => fileName(path) ?? 'unknown')
    for (let round = 0; round < 10; round++) {
        const groups = new Map<string, number[]>()
        result.forEach((name, index) => {
            const group = groups.get(name)
            if (group) {
                group.push(index)
            } else {
                groups.set(name, [index])
            }
        })
        let duplicates = false
        for (const indices of groups.values()) {
            if (indices.length < 2) {
                continue
            }
            duplicates = true
            for (const index of indices) {
                // Dot components never disambiguate, and `..` would let a crafted DWARF path escape
                // `__source/` when the zip is extracted.
                const components = paths[index]!.split('/').filter(
                    (part) => part !== '' && part !== '.' && part !== '..'
                )
                const depth = Math.min(result[index]!.split('/').length + 1, components.length)
                result[index] = components.slice(components.length - depth).join('/')
            }
        }
        if (!duplicates) {
            break
        }
    }
    return result
}

// `read_source_file`: a DWARF path can point anywhere, so symlinks, devices and files over 64 MiB
// are refused, and the checks run on the opened file. O_NONBLOCK keeps the open of a FIFO
// without a writer from hanging before the regular-file check rejects it.
function readSourceFile(path: string): Uint8Array {
    if (lstatSync(path).isSymbolicLink()) {
        throw new Error('path is a symlink')
    }
    const descriptor = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK)
    try {
        const stat = fstatSync(descriptor)
        if (!stat.isFile()) {
            throw new Error('not a regular file')
        }
        if (stat.size > MAX_SOURCE_FILE_BYTES) {
            throw new Error('exceeds the source file size limit')
        }
        // Like Rust's `take(MAX + 1)`, a file that grew since the stat is read up to the cap.
        let buffer = Buffer.alloc(stat.size + 1)
        let total = 0
        for (;;) {
            if (total === buffer.length) {
                if (total > MAX_SOURCE_FILE_BYTES) {
                    throw new Error('exceeds the source file size limit')
                }
                const grown = Buffer.alloc(Math.min(buffer.length * 2, MAX_SOURCE_FILE_BYTES + 1))
                buffer.copy(grown)
                buffer = grown
            }
            const count = readSync(descriptor, buffer, total, buffer.length - total, null)
            if (count === 0) {
                return buffer.subarray(0, total)
            }
            total += count
        }
    } finally {
        closeSync(descriptor)
    }
}

// `collect_source_files`. Files that can't be read are reported and left out, and the manifest is
// written even when every read failed.
export function collectSources(paths: string[], warnings: string[]): SourceBundle {
    const bundle: SourceBundle = { manifest: new Map(), contents: new Map() }
    zipRelativePaths(paths).forEach((relative, index) => {
        const path = paths[index]!
        try {
            const data = readSourceFile(path)
            const zipPath = `__source/${relative}`
            bundle.manifest.set(path, zipPath)
            bundle.contents.set(zipPath, data)
        } catch (error) {
            warnings.push(`hog couldn't read the source file ${path}, so it isn't bundled: ${(error as Error).message}`)
        }
    })
    return bundle
}

// `serde_json::to_vec_pretty` of `SourceManifest { version, files: BTreeMap }`.
function manifestJson(manifest: Map<string, string>): string {
    const entries = [...manifest].sort(([a], [b]) => compareUtf8(a, b))
    const files =
        entries.length === 0
            ? '{}'
            : `{\n${entries.map(([key, value]) => `    ${writeString(key)}: ${writeString(value)}`).join(',\n')}\n  }`
    return `{\n  "version": 1,\n  "files": ${files}\n}`
}

// `add_source_to_zip`: the manifest, then every file in zip-path byte order.
export function addSources(zip: ZipWriter, bundle: SourceBundle): void {
    zip.add('__source/manifest.json', Buffer.from(manifestJson(bundle.manifest), 'utf8'))
    for (const [path, data] of [...bundle.contents].sort(([a], [b]) => compareUtf8(a, b))) {
        zip.add(path, data)
    }
}

export type SourceFilter = 'dsym' | 'native'

// The source paths of one binary, filtered as `dsym upload` or `symbol-sets upload` filters them.
// A DWARF error means no sources. posthog-cli logs the same and uploads the binary alone.
export function sourcePaths(source: Source, filter: SourceFilter, warnings: string[]): string[] {
    let all: string[]
    try {
        all = extractSourcePaths(source)
    } catch (error) {
        warnings.push(
            `hog couldn't read the source paths from the DWARF, so it uploads without sources: ${(error as Error).message}`
        )
        return []
    }
    return filter === 'dsym' ? filterSourcePaths(all) : filterNativeSourcePaths(all)
}

// Kernel-backed files hold no source code, but some hold secrets, like /proc/self/environ. Their
// bytes change with every process, so posthog-cli can never upload the same ones.
const VIRTUAL_FILESYSTEMS = ['/proc/', '/sys/', '/dev/']
const isVirtual = (path: string): boolean => {
    let real: string
    try {
        real = realpathSync(path)
    } catch {
        return false
    }
    return VIRTUAL_FILESYSTEMS.some((prefix) => real.startsWith(prefix))
}

export function sourceStep(
    bytes: Uint8Array,
    filter: SourceFilter,
    warnings: string[],
    ignored: (path: string) => boolean
): ((zip: ZipWriter) => void) | undefined {
    const paths = sourcePaths(new BufferSource(bytes), filter, warnings).filter(
        (path) => !ignored(path) && !isVirtual(path)
    )
    if (paths.length === 0) {
        return undefined
    }
    const bundle = collectSources(paths, warnings)
    return (zip) => addSources(zip, bundle)
}
