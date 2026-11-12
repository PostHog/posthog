import { defineCommand } from '@/core/command'
import { HogError } from '@/core/errors'

const LISTED_NAMES = 8

function toolNames(catalog: { tools: unknown[] } | undefined): Set<string> {
    const names = new Set<string>()
    for (const tool of catalog?.tools ?? []) {
        const name = (tool as { name?: unknown } | null)?.name
        if (typeof name === 'string') {
            names.add(name)
        }
    }
    return names
}

function listed(names: string[]): string {
    const shown = names.slice(0, LISTED_NAMES).join(', ')
    return names.length > LISTED_NAMES ? `${shown} and ${names.length - LISTED_NAMES} more` : shown
}

export default defineCommand({
    description: 'Download the newest API tool catalog now, instead of waiting for the daily check',
    notes: 'hog checks for a new catalog at most once a day, when a `hog api` command runs. HOG_API_CATALOG=bundled keeps the tools built into hog.',
    examples: ['hog api refresh'],

    async run({ ctx }) {
        const library = await ctx.apiTools({ refresh: true })
        const resolved = ctx.catalog
        const status = library.catalog()

        if (!resolved?.catalog || status.source !== 'downloaded') {
            const needsNewerHog = status.rejected !== null || resolved?.reasonCode === 'needs_newer_hog'
            const hints: Partial<Record<string, string>> = {
                needs_newer_hog: 'Update hog to get the newest tools.',
                pinned: 'Unset HOG_API_CATALOG to download the catalog.',
                self_hosted: 'Self-hosted PostHog uses the tools built into hog.',
            }
            throw new HogError(
                'catalog_not_used',
                `hog uses the tools built into it, because ${status.rejected ?? resolved?.reason ?? 'the catalog could not be used'}.`,
                hints[needsNewerHog ? 'needs_newer_hog' : (resolved?.reasonCode ?? '')]
            )
        }

        // A new tool this hog can't run isn't new to the person, so it's reported as unavailable instead.
        const unavailable = new Set(status.dropped.filter((tool) => !tool.builtIn).map((tool) => tool.name))
        const before = toolNames(resolved.previous)
        const after = toolNames(resolved.catalog)
        const added = [...after].filter((name) => !before.has(name) && !unavailable.has(name)).sort()
        const removed = [...before].filter((name) => !after.has(name)).sort()
        const unchanged = resolved.previous?.build === resolved.catalog.build && added.length + removed.length === 0

        return {
            status: unchanged ? ('unchanged' as const) : ('updated' as const),
            tools: status.tools,
            build: status.build,
            fetchedAt: new Date(resolved.fetchedAt ?? Date.now()).toISOString(),
            added,
            removed,
            dropped: status.dropped,
        }
    },
    human({ result, out }) {
        const count = (n: number, noun: string): string => (n === 1 ? `one ${noun}` : `${n} ${noun}s`)
        const kept = result.dropped.filter((tool) => tool.builtIn)
        const unavailable = result.dropped.filter((tool) => !tool.builtIn)
        const dropped = [
            ...(kept.length
                ? [
                      `hog keeps its built-in version of ${count(kept.length, 'tool')}, because it can't run the new one:`,
                      ...kept.map((tool) => `  ${tool.name}: ${tool.reason}`),
                  ]
                : []),
            ...(unavailable.length
                ? [
                      `This hog can't run ${count(unavailable.length, 'new tool')} yet. Update hog to use ${unavailable.length === 1 ? 'it' : 'them'}:`,
                      ...unavailable.map((tool) => `  ${tool.name}: ${tool.reason}`),
                  ]
                : []),
        ]
        if (result.status === 'unchanged') {
            out.report({
                result: 'The API tool catalog is up to date',
                status: 'unchanged',
                effects: [`${result.tools} tools from the MCP server`],
                warnings: dropped,
            })
            return
        }
        out.report({
            result: 'Updated the API tool catalog',
            effects: [
                `${result.tools} tools from the MCP server`,
                ...(result.added.length ? [`New: ${listed(result.added)}`] : []),
                ...(result.removed.length ? [`Removed: ${listed(result.removed)}`] : []),
            ],
            warnings: dropped,
        })
    },
    agent({ result, out }) {
        out.json(result)
    },

    telemetry: ({ result }) => ({
        status: result.status,
        tool_count: result.tools,
        added_count: result.added.length,
        removed_count: result.removed.length,
        dropped_count: result.dropped.length,
    }),
})
