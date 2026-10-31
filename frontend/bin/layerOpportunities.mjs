// Ranks structural changes that would shrink the shell's eager graph or make the layer map tell the truth.
import { LAYERS, groupOf, layerOf } from './layers.mjs'

const MIN_SAVING_BYTES = 30 * 1024

function reachableBytes(files, root, isCut) {
    const seen = new Set([root])
    const queue = [root]
    let bytes = files[root]?.bytes ?? 0
    while (queue.length) {
        const from = queue.pop()
        for (const to of files[from]?.staticImports ?? []) {
            if (seen.has(to) || isCut(from, to)) {
                continue
            }
            seen.add(to)
            bytes += files[to]?.bytes ?? 0
            queue.push(to)
        }
    }
    return bytes
}

const rank = (file) => LAYERS.indexOf(layerOf(file))

function importersOf(files) {
    const importers = {}
    for (const [from, { staticImports }] of Object.entries(files)) {
        for (const to of staticImports) {
            ;(importers[to] ??= new Set()).add(from)
        }
    }
    return importers
}

// A feature or query folder that a few imports drag onto the eager path is the cheapest lazy-load win.
function lazyFolders(files, shellRoot, shellReach, total) {
    const folders = new Set([...shellReach.keys()].filter((f) => rank(f) > rank(shellRoot)).map(groupOf))
    return [...folders]
        .map((folder) => {
            const entries = []
            for (const from of shellReach.keys()) {
                if (groupOf(from) === folder) {
                    continue
                }
                for (const to of files[from].staticImports) {
                    if (groupOf(to) === folder) {
                        entries.push([from, to])
                    }
                }
            }
            const saved =
                total -
                reachableBytes(files, shellRoot, (from, to) => groupOf(to) === folder && groupOf(from) !== folder)
            return { folder, layer: layerOf([...shellReach.keys()].find((f) => groupOf(f) === folder)), saved, entries }
        })
        .filter((o) => o.saved >= MIN_SAVING_BYTES)
        .sort((a, b) => b.saved / b.entries.length - a.saved / a.entries.length)
}

// A file that lower layers lean on, and that leans on nothing above the lowest of them, sits in the wrong
// layer. Moving it down to that layer clears every upward import into it and adds none.
function misplacedFiles(files, importers) {
    return Object.keys(files)
        .map((file) => {
            const lowerImporters = [...(importers[file] ?? [])].filter((from) => rank(from) < rank(file))
            const lowest = Math.min(...lowerImporters.map(rank))
            const blocking = files[file].staticImports.filter((to) => rank(to) > lowest)
            return { file, layer: layerOf(file), moveTo: LAYERS[lowest], lowerImporters, blocking }
        })
        .filter((o) => o.lowerImporters.length >= 2 && o.blocking.length === 0)
        .sort((a, b) => b.lowerImporters.length - a.lowerImporters.length)
}

// A small file imported upward that pulls a large closure behind it usually mixes a cheap export with a heavy one.
function heavyHubs(files, shellRoot, shellReach, total) {
    const targets = new Set()
    for (const from of shellReach.keys()) {
        for (const to of files[from].staticImports) {
            if (rank(to) > rank(from)) {
                targets.add(to)
            }
        }
    }
    return [...targets]
        .map((file) => {
            const saved = total - reachableBytes(files, shellRoot, (_, to) => to === file)
            return { file, layer: layerOf(file), bytes: files[file].bytes, saved }
        })
        .filter((o) => o.saved >= MIN_SAVING_BYTES && o.saved >= 4 * o.bytes)
        .sort((a, b) => b.saved - a.saved)
}

// The kernel is the bottom layer, so every import out of it is a mistake in the code or in the map.
function kernelLeaks(files) {
    const kernelRank = LAYERS.indexOf('kernel')
    const byTarget = {}
    for (const [from, { staticImports }] of Object.entries(files)) {
        if (rank(from) !== kernelRank) {
            continue
        }
        for (const to of staticImports.filter((target) => rank(target) > kernelRank)) {
            ;(byTarget[to] ??= { file: to, layer: layerOf(to), importers: [] }).importers.push(from)
        }
    }
    return Object.values(byTarget).sort((a, b) => b.importers.length - a.importers.length)
}

export function findOpportunities({ files, shellRoot, shellReach }) {
    const total = reachableBytes(files, shellRoot, () => false)
    const importers = importersOf(files)
    return {
        lazyFolders: lazyFolders(files, shellRoot, shellReach, total),
        misplacedFiles: misplacedFiles(files, importers),
        heavyHubs: heavyHubs(files, shellRoot, shellReach, total),
        kernelLeaks: kernelLeaks(files),
    }
}
