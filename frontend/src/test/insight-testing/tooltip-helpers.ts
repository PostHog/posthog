import { createHogChartTooltip, type HogChartTooltip } from '@posthog/quill-charts/testing'

/** Insight-flavored tooltip accessor. Extends the generic hog-charts tooltip
 *  with helpers for reading a per-series tooltip. Insight charts render hog-charts'
 *  `DefaultTooltip` (`hog-chart-tooltip-*` rows); the legacy `InsightTooltip` table
 *  branch (`<th>` header, `<tr>` rows with `.datum-column` / `.datum-counts-column`)
 *  is retained for any remaining table-based tooltip readers. */
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
                // The series label mixes non-breaking spaces (e.g. the compare separator) with regular
                // ones, so normalize whitespace before matching against the caller's plain-space label.
                const normalize = (text: string | null | undefined): string => (text ?? '').replace(/\s+/g, ' ').trim()
                const needle = normalize(label)
                const row = defaultRows().find((r) =>
                    normalize(r.querySelector('[data-attr="hog-chart-tooltip-series"]')?.textContent).includes(needle)
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
