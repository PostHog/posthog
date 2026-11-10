import { SourceConfigResponseApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

export interface InlineSourceGrid {
    shown: SourceConfigResponseApi[]
    hiddenCount: number
}

/**
 * The tiles the inline source grid shows. Sources the setup agent found in the project's codebase lead,
 * and they count as featured, so a detected source never hides behind "Show more".
 */
export function inlineSourceGrid({
    connectors,
    detectedTypes,
    featuredOnly,
    query,
}: {
    connectors: SourceConfigResponseApi[]
    detectedTypes: ReadonlySet<string>
    featuredOnly: boolean
    query: string
}): InlineSourceGrid {
    const detectedFirst = [
        ...connectors.filter((c) => detectedTypes.has(c.name)),
        ...connectors.filter((c) => !detectedTypes.has(c.name)),
    ]
    const trimmedQuery = query.trim().toLowerCase()
    // A search matches every source; the featured split applies only to the unsearched view.
    if (trimmedQuery) {
        return {
            shown: detectedFirst.filter((c) => (c.label ?? c.name).toLowerCase().includes(trimmedQuery)),
            hiddenCount: 0,
        }
    }
    if (!featuredOnly) {
        return { shown: detectedFirst, hiddenCount: 0 }
    }
    const shown = detectedFirst.filter((c) => c.featured || detectedTypes.has(c.name))
    return { shown, hiddenCount: detectedFirst.length - shown.length }
}
