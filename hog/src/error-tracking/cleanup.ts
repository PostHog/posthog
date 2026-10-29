import { existsSync, readFileSync, realpathSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { dirname, isAbsolute, relative } from 'node:path'

import { contentHash } from './container'
import { decodeUtf8 } from './json'
import { findSourceMap, loadMapContent, rustTrim, serializeMapContent, type SourcePair } from './kinds/js'

// `--delete-after`: once an upload succeeded, drop the sourcemap references from the bundles and
// delete the maps, so they never ship to users. A file that changed since hog read it is left
// alone, and a map is only deleted when every bundle that points at it was cleaned.

export interface CleanupTarget {
    sourcePath: string
    mapPath: string
    sourceFingerprint: string
    mapFingerprint: string
    kind: 'js' | 'css'
}

export interface CleanupResult {
    deletedMaps: string[]
    warnings: string[]
}

export function jsTarget(pair: SourcePair): CleanupTarget {
    return {
        sourcePath: pair.sourcePath,
        mapPath: pair.mapPath,
        sourceFingerprint: pair.sourceFingerprint(),
        mapFingerprint: pair.mapFingerprint(),
        kind: 'js',
    }
}

// The last real line of a bundle, skipping blank lines and the chunk and debug id comments, when it
// is a `sourceMappingURL` comment: the whole line goes, newline included.
function jsReferenceRange(content: string): [number, number] | undefined {
    const lines: [number, number, string][] = []
    let start = 0
    for (const line of content.split(/(?<=\n)/)) {
        lines.push([start, start + line.length, line])
        start += line.length
    }
    for (const [lineStart, lineEnd, line] of lines.reverse()) {
        const trimmed = rustTrim(line)
        if (trimmed === '' || trimmed.startsWith('//# chunkId=') || trimmed.startsWith('//# debugId=')) {
            continue
        }
        if (trimmed.startsWith('//# sourceMappingURL=') || trimmed.startsWith('//@ sourceMappingURL=')) {
            return [lineStart, lineEnd]
        }
        return undefined
    }
    return undefined
}

const CSS_PREFIX = '/*# sourceMappingURL='

// The last `/*# sourceMappingURL=... */` comment outside a string, as posthog-cli's CSS lexer finds it.
function cssReferenceRange(content: string): [number, number] | undefined {
    let index = 0
    let quote: string | undefined
    let escaped = false
    let found: [number, number] | undefined
    while (index < content.length) {
        const char = content[index]!
        if (escaped) {
            escaped = false
            index++
            continue
        }
        if (quote !== undefined) {
            if (char === '\\') {
                escaped = true
            } else if (char === quote) {
                quote = undefined
            }
            index++
            continue
        }
        if (char === '\\') {
            escaped = true
            index++
        } else if (char === "'" || char === '"') {
            quote = char
            index++
        } else if (char === '/' && content[index + 1] === '*') {
            const close = content.indexOf('*/', index + 2)
            if (close < 0) {
                return undefined
            }
            const end = close + 2
            if (content.startsWith(CSS_PREFIX, index)) {
                found = [index, end]
            }
            index = end
        } else {
            index++
        }
    }
    return found
}

export function cssReference(content: string): string | undefined {
    const range = cssReferenceRange(content)
    return range ? content.slice(range[0] + CSS_PREFIX.length, range[1] - 2).trimEnd() : undefined
}

function cssRemovalRange(content: string): [number, number] | undefined {
    const range = cssReferenceRange(content)
    if (!range) {
        return undefined
    }
    const lineStart = content.lastIndexOf('\n', range[0] - 1) + 1
    const newline = content.indexOf('\n', range[1])
    const lineEnd = newline < 0 ? content.length : newline + 1
    const blank = (text: string): boolean => text.trim() === ''
    return blank(content.slice(lineStart, range[0])) && blank(content.slice(range[1], lineEnd))
        ? [lineStart, lineEnd]
        : range
}

// CSS bundles with maps under the given roots. Their maps are cleaned up too, but only when they
// resolve inside a root, so a stylesheet can't make hog delete a file elsewhere. A map that an
// ignore glob excludes, or a JSON file that isn't a sourcemap, is left alone.
export function cssTargets(
    files: string[],
    roots: string[],
    publicPathPrefix: string | undefined,
    warnings: string[],
    ignored: (mapPath: string) => boolean
): CleanupTarget[] {
    const canonicalRoots = roots.map((root) => {
        const absolute = realpathSync(root)
        return statSync(absolute).isFile() ? dirname(absolute) : absolute
    })
    const targets: CleanupTarget[] = []
    for (const file of files.filter((path) => path.endsWith('.css'))) {
        let source: string
        let mapPath: string | undefined
        try {
            source = decodeUtf8(readFileSync(realpathSync(file)))
            mapPath = findSourceMap(realpathSync(file), cssReference(source), publicPathPrefix)
        } catch {
            warnings.push(`Skipping sourcemap cleanup for ${file}: its sourcemap reference can't be read.`)
            continue
        }
        if (mapPath === undefined || ignored(mapPath)) {
            continue
        }
        let map
        try {
            map = loadMapContent(decodeUtf8(readFileSync(mapPath)))
        } catch {
            continue
        }
        if (!map.fields.has('mappings') && !map.fields.has('sections')) {
            continue
        }
        const canonicalMap = realpathSync(mapPath)
        // On Windows, `relative` returns an absolute path for a file on another drive.
        const inside = (root: string): boolean => {
            const within = relative(root, canonicalMap)
            return !within.startsWith('..') && !isAbsolute(within)
        }
        if (!canonicalRoots.some(inside)) {
            warnings.push(
                `Skipping CSS sourcemap cleanup for ${mapPath} because it resolves outside the selected paths.`
            )
            continue
        }
        targets.push({
            sourcePath: realpathSync(file),
            mapPath,
            sourceFingerprint: contentHash(source),
            mapFingerprint: contentHash(serializeMapContent(map)),
            kind: 'css',
        })
    }
    return targets
}

export function cleanUp(targets: CleanupTarget[]): CleanupResult {
    const warnings: string[] = []
    const skippedMaps = new Set<string>()
    const maps = new Map<string, Set<string>>()
    for (const target of targets) {
        const canonicalMap = existsSync(target.mapPath) ? realpathSync(target.mapPath) : target.mapPath
        if (!maps.has(canonicalMap)) {
            maps.set(canonicalMap, new Set())
        }
        maps.get(canonicalMap)!.add(target.mapFingerprint)
        if (!existsSync(target.sourcePath)) {
            warnings.push(`Skipping cleanup for ${target.sourcePath}: the file no longer exists.`)
            skippedMaps.add(canonicalMap)
            continue
        }
        const content = decodeUtf8(readFileSync(target.sourcePath))
        if (contentHash(content) !== target.sourceFingerprint) {
            warnings.push(`Skipping cleanup for ${target.sourcePath}: the file changed since it was uploaded.`)
            skippedMaps.add(canonicalMap)
            continue
        }
        const range = target.kind === 'js' ? jsReferenceRange(content) : cssRemovalRange(content)
        if (range) {
            writeFileSync(target.sourcePath, content.slice(0, range[0]) + content.slice(range[1]))
        }
    }
    const deletedMaps: string[] = []
    for (const [path, fingerprints] of maps) {
        if (skippedMaps.has(path)) {
            warnings.push(`Skipping sourcemap deletion for ${path}: a source referencing it was skipped.`)
            continue
        }
        if (!existsSync(path)) {
            continue
        }
        let current: string
        try {
            current = contentHash(serializeMapContent(loadMapContent(decodeUtf8(readFileSync(path)))))
        } catch {
            current = ''
        }
        if (!fingerprints.has(current)) {
            warnings.push(`Skipping sourcemap deletion for ${path}: the map changed since it was uploaded.`)
            continue
        }
        rmSync(path)
        deletedMaps.push(path)
    }
    return { deletedMaps, warnings }
}
