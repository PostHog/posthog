import { createHogChartTooltip, type HogChartTooltip } from 'lib/hog-charts/testing'

/** Insight-flavored tooltip accessor. Extends the generic hog-charts tooltip
 *  with helpers for the InsightTooltip's table layout — a header `<th>` row
 *  and per-series `<tr>` rows with `.datum-column` / `.datum-counts-column`
 *  cells. Other consumers with their own tooltip renderer should compose
 *  their own accessor on top of `createHogChartTooltip` the same way. */
export interface InsightTooltipAccessor extends HogChartTooltip {
    /** Header text — typically the hovered date (e.g. "Wednesday, 12 Jun (UTC)"). */
    title(): string
    /** Value cell text for the row whose datum column contains `label`. */
    row(label: string): string | undefined
    /** Ordered list of row datum labels (skips the header row). */
    rows(): string[]
}

export function createInsightTooltipAccessor(element: HTMLElement): InsightTooltipAccessor {
    return Object.assign(createHogChartTooltip(element), {
        title(): string {
            return element.querySelector('thead th')?.textContent?.trim() ?? ''
        },

        row(label: string): string | undefined {
            const rows = element.querySelectorAll('tbody tr')
            for (let i = 0; i < rows.length; i++) {
                const row = rows[i]
                if (row.textContent?.includes(label)) {
                    const cell = row.querySelector('.datum-counts-column')
                    return cell?.textContent ?? undefined
                }
            }
            return undefined
        },

        rows(): string[] {
            const rows = element.querySelectorAll('tbody tr')
            return Array.from(rows)
                .map((r) => r.querySelector('.datum-column')?.textContent?.trim() ?? '')
                .filter(Boolean)
        },
    })
}
