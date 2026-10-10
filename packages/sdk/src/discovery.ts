import type { ToolCatalog, ToolDescription, ToolSearchOptions, ToolSearchResult } from './discovery-types.js'
import { catalog as generatedCatalog, descriptions } from './generated/discovery.js'

export type * from './discovery-types.js'

/** Static metadata: importing discovery does not load credentials or the API runtime. */
export const catalog: ToolCatalog = structuredClone(generatedCatalog)

export function searchTools(query: string, options: ToolSearchOptions = {}): ToolSearchResult[] {
    const limit = options.limit ?? 10
    if (!Number.isInteger(limit) || limit < 1 || limit > 100) {
        throw new RangeError('Search limit must be an integer between 1 and 100.')
    }
    const terms = query
        .toLowerCase()
        .split(/[^a-z0-9]+/)
        .filter(Boolean)
    const scores = descriptions.map((description) => {
        const names =
            `${description.method} ${description.toolName} ${description.title} ${description.selectionHint ?? ''}`.toLowerCase()
        const all = `${names} ${description.description.toLowerCase()}`
        const score = terms.every((term) => all.includes(term))
            ? terms.reduce((sum, term) => sum + (names.includes(term) ? 5 : 1), 1)
            : 0
        return { description, score }
    })
    return scores
        .filter((item) => item.score > 0)
        .sort((a, b) => b.score - a.score || a.description.method.localeCompare(b.description.method))
        .slice(0, limit)
        .map(({ description }) =>
            structuredClone(generatedCatalog.tools.find((tool) => tool.method === description.method)!)
        )
}

export function describeTool(methodOrToolName: string): ToolDescription | undefined {
    const description = descriptions.find(
        (tool) => tool.method === methodOrToolName || tool.toolName === methodOrToolName
    )
    if (!description) {
        return undefined
    }
    return JSON.parse(
        readFileSync(new URL(`../${description.descriptionFile}`, import.meta.url), 'utf8')
    ) as ToolDescription
}
import { readFileSync } from 'node:fs'
