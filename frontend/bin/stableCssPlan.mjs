import { CSS_LOAD_GLOBAL } from '@posthog/esbuilder/cssLoader.mjs'
import { chunkIdentity, shortHash } from '@posthog/esbuilder/stableChunkNames.mjs'

import { BOOT_ENTRIES, ENTRY } from './bootEntries.mjs'

/**
 * Split stylesheets for the stable build.
 *
 * esbuild puts the CSS of every chunk, lazy ones included, into the entry's stylesheet, so every
 * page downloads and parses all of the app's CSS before its first render. This step splits the
 * same CSS into groups and builds each group as its own stylesheet, named by its own content:
 *
 * - Eager layers hold the CSS that the boot chain (entry, App, bootApp, AuthenticatedShell) imports
 *   statically. The stable page links them in order before the first render.
 * - Lazy groups hold the rest, grouped by the JS chunks whose modules import it. A lazy entry
 *   chunk waits for the groups its static imports need before it runs (see `cssPrelude`).
 *
 * Groups keep today's rule order among themselves, because every group lists its files in the
 * order of the entry stylesheet. Lazy groups load after the eager layers.
 */

export const CSS_SPECIFIER_PREFIX = '@css/'

const isStylesheet = (file) => /\.(css|scss|sass)$/.test(file)

function eagerLayer(file) {
    if (file.endsWith('tailwind/tailwind.css')) {
        return 'eager-tailwind'
    }
    if (file.endsWith('src/styles/global.scss')) {
        return 'eager-global'
    }
    return 'eager-app'
}
const EAGER_ORDER = ['eager-tailwind', 'eager-global', 'eager-app']

/**
 * Plans the groups from the app build's metafile. Pure.
 *
 * Returns `groups` (name -> source files in rule order), `eager` (layer names in link order) and
 * `lazyGroupsByEntry` (lazy entry output path -> the lazy groups its static imports need).
 */
export function planCssGroups({ inputs, outputs }, bootEntries = BOOT_ENTRIES) {
    const entryOutput = (entryPoint) =>
        Object.keys(outputs).find((file) => outputs[file].entryPoint === entryPoint && file.endsWith('.js'))
    const linkedStylesheet = outputs[entryOutput(ENTRY)]?.cssBundle
    if (!linkedStylesheet) {
        throw new Error('stable css: the entry has no stylesheet to split')
    }
    const order = Object.keys(outputs[linkedStylesheet].inputs)
    const rank = new Map(order.map((file, index) => [file, index]))

    const boot = new Set(bootEntries.filter((entry) => inputs[entry]))
    for (const queue = [...boot]; queue.length; ) {
        for (const imported of inputs[queue.shift()].imports || []) {
            if (imported.kind === 'import-statement' && inputs[imported.path] && !boot.has(imported.path)) {
                boot.add(imported.path)
                queue.push(imported.path)
            }
        }
    }

    const outputOfInput = new Map()
    for (const [file, output] of Object.entries(outputs)) {
        if (file.endsWith('.js')) {
            for (const input of Object.keys(output.inputs)) {
                outputOfInput.set(input, file)
            }
        }
    }
    const ownersOfStylesheet = new Map()
    for (const [file, input] of Object.entries(inputs)) {
        for (const imported of input.imports || []) {
            if (isStylesheet(imported.path) && outputOfInput.has(file)) {
                const owners = ownersOfStylesheet.get(imported.path) ?? new Set()
                owners.add(outputOfInput.get(file))
                ownersOfStylesheet.set(imported.path, owners)
            }
        }
    }

    const groups = new Map()
    const groupsOfChunk = new Map()
    // A lazy group is a run of adjacent files with the same owners, so it holds its rules in the
    // same order as the entry stylesheet. Merging non-adjacent files would move the rules of the
    // files between them. A run is named by its owners' identities, which do not change when code
    // does, and by its first file, so a file added elsewhere does not rename it.
    let previousOwnersKey = null
    let runName = null
    for (const file of order) {
        let name
        if (boot.has(file)) {
            name = eagerLayer(file)
            previousOwnersKey = null
        } else {
            const owners = [...(ownersOfStylesheet.get(file) ?? [])]
            const ownersKey = owners
                .map((owner) => chunkIdentity(outputs[owner]))
                .sort()
                .join('\n')
            if (ownersKey !== previousOwnersKey) {
                runName = `lazy-${shortHash(`${ownersKey}\n${file}`)}`
                previousOwnersKey = ownersKey
            }
            name = runName
            for (const owner of owners) {
                const names = groupsOfChunk.get(owner) ?? new Set()
                names.add(name)
                groupsOfChunk.set(owner, names)
            }
        }
        groups.set(name, [...(groups.get(name) ?? []), file])
    }

    // The layers link in EAGER_ORDER, which only matches the cascade while the boot stylesheets come
    // in that order in the entry stylesheet. Fail the build rather than reorder rules silently.
    const layerIndexes = order.filter((file) => boot.has(file)).map((file) => EAGER_ORDER.indexOf(eagerLayer(file)))
    if (layerIndexes.some((index, i) => i > 0 && index < layerIndexes[i - 1])) {
        throw new Error('stable css: boot stylesheets are not in layer order, so splitting them would reorder rules')
    }

    const firstRank = (name) => rank.get(groups.get(name)[0])
    const lazyGroupsByEntry = new Map()
    const bootOutputs = new Set(bootEntries.map(entryOutput))
    for (const [file, output] of Object.entries(outputs)) {
        if (!file.endsWith('.js') || !output.entryPoint || bootOutputs.has(file)) {
            continue
        }
        const needed = new Set()
        const seen = new Set([file])
        for (const queue = [file]; queue.length; ) {
            const current = queue.shift()
            for (const name of groupsOfChunk.get(current) ?? []) {
                needed.add(name)
            }
            for (const imported of outputs[current].imports || []) {
                if (imported.kind === 'import-statement' && outputs[imported.path] && !seen.has(imported.path)) {
                    seen.add(imported.path)
                    queue.push(imported.path)
                }
            }
        }
        if (needed.size) {
            lazyGroupsByEntry.set(
                file,
                [...needed].sort((a, b) => firstRank(a) - firstRank(b))
            )
        }
    }

    const eager = EAGER_ORDER.filter((name) => groups.has(name))
    // A lazy prelude would call the undefined window.ESBUILD_LOAD_CSS if there's no eager layer to define it.
    if (lazyGroupsByEntry.size > 0 && eager.length === 0) {
        throw new Error('stable css: lazy chunks need split CSS but no eager layer would define the loader')
    }

    // Each group's place in the entry stylesheet, so the loader can keep lazy groups in that order
    // whatever order scenes load them in.
    const rankOfGroup = new Map([...groups.keys()].map((name) => [name, firstRank(name)]))
    return { groups, eager, lazyGroupsByEntry, rankOfGroup }
}

/**
 * The line a lazy entry chunk starts with: it waits for its stylesheets before any of its code
 * runs, so the chunk never renders unstyled. `import.meta.resolve` reads each group's URL from the
 * import map, and the group's rank tells the loader where to insert it.
 *
 * A browser without `import.meta.resolve` (Chromium 89 to 104 has import maps but not this) gets
 * the full stylesheet instead. When even that fails, the chunk throws a ChunkLoadError, so the
 * app's chunk-load recovery runs, not an unstyled scene.
 */
export function cssPrelude(groupNames, rankOfGroup) {
    const entries = groupNames.map(
        (name) => `[import.meta.resolve(${JSON.stringify(CSS_SPECIFIER_PREFIX + name)}),${rankOfGroup.get(name)}]`
    )
    return (
        `if(!(await window.${CSS_LOAD_GLOBAL}(typeof import.meta.resolve=="function"?[${entries.join(',')}]:null)))` +
        `throw Object.assign(new Error("Stylesheets for this chunk did not load"),{name:"ChunkLoadError"});`
    )
}
