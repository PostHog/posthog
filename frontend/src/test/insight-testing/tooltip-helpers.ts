import { createHogChartTooltip, type HogChartTooltip } from '@posthog/quill-charts/testing'

/** Insight-flavored tooltip accessor. Extends the generic hog-charts tooltip
 *  with helpers for reading a per-series tooltip. Dual-mode: trends-family charts
 *  render hog-charts' `DefaultTooltip` (`hog-chart-tooltip-*` rows), while funnel
 *  and retention still render the legacy `InsightTooltip` table (`<th>` header,
 *  `<tr>` rows with `.datum-column` / `.datum-counts-column`). The accessor reads
 *  whichever is present so a single helper covers both during the migration. */
export interface InsightTooltipAccessor extends HogChartTooltip {
    /** Header text — typically the hovered date (e.g. "Wednesday, 12 Jun (UTC)"). */
    title(): string
    /** Value cell text for the row whose label contains `label`. */
    row(label: string): string | undefined
    /** Ordered list of row labels (skips the header). */
    rows(): string[]
}

export function createInsightTooltipAccessor(element: HTMLElement): InsightTooltipAccessor {
    const isDefaultTooltip = (): boolean => !!element.querySelector('[data-attr="hog-chart-tooltip-label"]')
    const defaultRows = (): HTMLElement[] =>
        Array.from(element.querySelectorAll<HTMLElement>('[data-attr="hog-chart-tooltip-row"]'))

    return Object.assign(createHogChartTooltip(element), {
        title(): string {
            if (isDefaultTooltip()) {
                return element.querySelector('[data-attr="hog-chart-tooltip-label"]')?.textContent?.trim() ?? ''
            }
            return element.querySelector('thead th')?.textContent?.trim() ?? ''
        },

        row(label: string): string | undefined {
            if (isDefaultTooltip()) {
                const row = defaultRows().find((r) =>
                    r.querySelector('[data-attr="hog-chart-tooltip-series"]')?.textContent?.includes(label)
                )
                return row?.querySelector('[data-attr="hog-chart-tooltip-value"]')?.textContent ?? undefined
            }
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
            if (isDefaultTooltip()) {
                return defaultRows()
                    .map((r) => r.querySelector('[data-attr="hog-chart-tooltip-series"]')?.textContent?.trim() ?? '')
                    .filter(Boolean)
            }
            const rows = element.querySelectorAll('tbody tr')
            return Array.from(rows)
                .map((r) => r.querySelector('.datum-column')?.textContent?.trim() ?? '')
                .filter(Boolean)
        },
    })
}
