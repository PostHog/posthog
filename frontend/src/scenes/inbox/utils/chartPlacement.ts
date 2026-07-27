// Where a report's charts go: which `chart:` references in the summary draw a chart at that point in
// the prose, and (by omission) which charts render after it instead.
//
// This parses the summary rather than pattern-matching it. A regex over the raw markdown disagrees
// with what the renderer actually does — it misses a link carrying a title (`[x](chart:a "note")`),
// matches inside a code span the renderer shows as literal text, and can't see that a reference sits
// in a table cell too narrow to hold a chart. Each disagreement costs a chart: one drawn twice,
// one drawn nowhere, one squashed to a sliver. So placement comes from the same markdown parse the
// renderer runs, and the renderer resolves each reference by its position in the source.

import { fromMarkdown } from 'mdast-util-from-markdown'
import { gfmTableFromMarkdown } from 'mdast-util-gfm-table'
import { gfmTable } from 'micromark-extension-gfm-table'

import { CHART_REF_PREFIX } from 'lib/lemon-ui/LemonMarkdown'

// Matched against the id charset the backend enforces on `chart_id` (see `ChartArtefact`).
const CHART_REF_TARGET = new RegExp(`^${CHART_REF_PREFIX}([a-z0-9][a-z0-9_-]*)$`)

// Nodes whose contents have no room for a chart. A table cell is a few dozen pixels wide; a heading
// is a line of text. A reference in one still reads as its label, and its chart falls to the end of
// the report rather than being dropped.
const NO_CHART_CONTAINERS = new Set(['heading', 'tableCell'])

export interface ChartPlacements {
    /** Source offset of each reference that draws a chart there → the chart id it draws. */
    inlineByOffset: Map<number, string>
    /** Ids drawn somewhere in the prose. Every other chart renders after the summary. */
    inlineIds: Set<string>
}

/** Only the table extension: it's the one GFM construct that changes where a chart reference lands. */
function parseSummary(summary: string): { children?: unknown[] } | null {
    try {
        return fromMarkdown(summary, {
            extensions: [gfmTable()],
            mdastExtensions: [gfmTableFromMarkdown()],
        })
    } catch {
        // A summary this parser chokes on leaves every chart trailing the prose rather than none at all.
        return null
    }
}

/**
 * Resolve where each of a report's charts is drawn, from its summary's markdown.
 *
 * Only the first reference to an id places it — repeating a reference reads as pointing back at the
 * chart, not as asking for a second copy of it, and each extra copy would fire the query again.
 */
export function resolveChartPlacements(
    summary: string | null | undefined,
    chartIds: Iterable<string>
): ChartPlacements {
    const inlineByOffset = new Map<number, string>()
    const inlineIds = new Set<string>()
    const available = new Set(chartIds)
    if (typeof summary !== 'string' || !summary || available.size === 0) {
        return { inlineByOffset, inlineIds }
    }
    const tree = parseSummary(summary)
    if (!tree) {
        return { inlineByOffset, inlineIds }
    }

    const visit = (node: any, hasRoom: boolean): void => {
        const roomHere = hasRoom && !NO_CHART_CONTAINERS.has(node?.type)
        if (roomHere && node?.type === 'link') {
            const chartId = CHART_REF_TARGET.exec(typeof node.url === 'string' ? node.url : '')?.[1]
            const offset = node.position?.start?.offset
            if (chartId && available.has(chartId) && !inlineIds.has(chartId) && typeof offset === 'number') {
                inlineByOffset.set(offset, chartId)
                inlineIds.add(chartId)
            }
        }
        for (const child of node?.children ?? []) {
            visit(child, roomHere)
        }
    }
    visit(tree, true)

    return { inlineByOffset, inlineIds }
}
