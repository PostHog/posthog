import { createHash } from 'node:crypto'

import { CSS_LOAD_GLOBAL } from '@posthog/esbuilder/cssLoader.mjs'
import { chunkIdentity } from '@posthog/esbuilder/stableChunkNames.mjs'

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

// The same roots as the logged-out and authenticated boot in bin/check-eager-graph.mjs.
const BOOT_ENTRIES = [
    'src/index.tsx',
    'src/scenes/App.tsx',
    'src/scenes/bootApp.ts',
    'src/scenes/AuthenticatedShell.tsx',
]
const isStylesheet = (file) => /\.(s?css|sass)$/.test(file)

function shortHash(value) {
    return createHash('sha256').update(value).digest('hex').slice(0, 10).toUpperCase()
}

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
    const linkedStylesheet = outputs[entryOutput('src/index.tsx')]?.cssBundle
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
    const nameOfFile = new Map()
    for (const file of order) {
        let name
        if (boot.has(file)) {
            name = eagerLayer(file)
        } else {
            // Named by the identities of the chunks that import it, which do not change when code does.
            const owners = [...(ownersOfStylesheet.get(file) ?? [])]
            name = `lazy-${shortHash(
                owners
                    .map((owner) => chunkIdentity(outputs[owner]))
                    .sort()
                    .join('\n')
            )}`
            for (const owner of owners) {
                const names = groupsOfChunk.get(owner) ?? new Set()
                names.add(name)
                groupsOfChunk.set(owner, names)
            }
        }
        nameOfFile.set(file, name)
        groups.set(name, [...(groups.get(name) ?? []), file])
    }

    // The layers link in EAGER_ORDER, which only matches the cascade while the boot stylesheets come
    // in that order in the entry stylesheet. Fail the build rather than reorder rules silently.
    const layerIndexes = order.filter((file) => boot.has(file)).map((file) => EAGER_ORDER.indexOf(eagerLayer(file)))
    if (layerIndexes.some((index, i) => i > 0 && index < layerIndexes[i - 1])) {
        throw new Error('stable css: boot stylesheets are not in layer order, so splitting them would reorder rules')
    }

    // Non-contiguous lazy groups would reorder rules against the group interleaved between them.
    let openLazyName = null
    const closedLazyNames = new Set()
    for (const file of order.filter((f) => !boot.has(f))) {
        const name = nameOfFile.get(file)
        if (name !== openLazyName) {
            if (closedLazyNames.has(name)) {
                throw new Error(
                    `stable css: lazy CSS group "${name}" is not contiguous, so splitting it would reorder rules`
                )
            }
            if (openLazyName !== null) {
                closedLazyNames.add(openLazyName)
            }
            openLazyName = name
        }
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

    return { groups, eager, lazyGroupsByEntry }
}

/**
 * The line a lazy entry chunk starts with: it waits for its stylesheets before any of its code
 * runs, so the chunk never renders unstyled. `import.meta.resolve` reads the URLs from the import map.
 */
export function cssPrelude(groupNames) {
    const urls = groupNames.map((name) => `import.meta.resolve(${JSON.stringify(CSS_SPECIFIER_PREFIX + name)})`)
    return `await window.${CSS_LOAD_GLOBAL}([${urls.join(',')}]);`
}
