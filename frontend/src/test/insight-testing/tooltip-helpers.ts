import { createHogChartTooltip, type HogChartTooltip } from '@posthog/quill-charts/testing'

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

/** Accessor for quill's `DefaultTooltip` layout, which SQL charts render (rather than the
 *  InsightTooltip table). Each series row is a flex div of `swatch span` + `<span>Label:</span>`
 *  + `<strong>value</strong>`; an optional total row swaps the swatch for an empty spacer. */
export interface SqlTooltipAccessor extends HogChartTooltip {
    /** Header text — the hovered x-axis label. */
    title(): string
    /** Formatted value for the series row whose label matches. */
    row(label: string): string | undefined
    /** Ordered series labels (excludes the total row). */
    rows(): string[]
    /** Per-series swatch colors (inline `background-color`), in row order. */
    swatchColors(): string[]
    /** Formatted total-row value, or undefined when no total row is shown. */
    total(): string | undefined
}

// jsdom's `:scope >` combinator leaks to descendants, so direct-child lookups go through `children`.
const directChildren = <T extends Element = HTMLElement>(el: HTMLElement, tag: string): T[] =>
    Array.from(el.children).filter((c): c is T => c.tagName === tag)

const sqlRowValue = (row: HTMLElement): HTMLElement | undefined => directChildren<HTMLElement>(row, 'STRONG')[0]

/** A "value row" is a flex div whose direct children include a `<strong>` (a series or total row). */
const sqlValueRows = (element: HTMLElement): HTMLElement[] =>
    Array.from(element.querySelectorAll<HTMLElement>('div')).filter((d) => sqlRowValue(d))

const sqlRowLabel = (row: HTMLElement): string => {
    const labelSpan = directChildren<HTMLElement>(row, 'SPAN').find((s) => (s.textContent ?? '').trim().endsWith(':'))
    return (labelSpan?.textContent ?? '').replace(/:\s*$/, '').trim()
}

const sqlRowSwatch = (row: HTMLElement): HTMLElement | undefined =>
    directChildren<HTMLElement>(row, 'SPAN').find((s) => !!s.style.backgroundColor)

export function createSqlTooltipAccessor(element: HTMLElement): SqlTooltipAccessor {
    const seriesRows = (): HTMLElement[] => sqlValueRows(element).filter((r) => sqlRowSwatch(r))
    const totalRow = (): HTMLElement | undefined => sqlValueRows(element).find((r) => !sqlRowSwatch(r))

    return Object.assign(createHogChartTooltip(element), {
        title(): string {
            // The label header is the lone childless div carrying text.
            const header = Array.from(element.querySelectorAll<HTMLElement>('div')).find(
                (d) => d.children.length === 0 && (d.textContent ?? '').trim().length > 0
            )
            return header?.textContent?.trim() ?? ''
        },

        row(label: string): string | undefined {
            const row = seriesRows().find((r) => sqlRowLabel(r) === label)
            return row ? (sqlRowValue(row)?.textContent ?? undefined) : undefined
        },

        rows(): string[] {
            return seriesRows().map(sqlRowLabel)
        },

        swatchColors(): string[] {
            return seriesRows().map((r) => sqlRowSwatch(r)?.style.backgroundColor ?? '')
        },

        total(): string | undefined {
            const row = totalRow()
            return row ? (sqlRowValue(row)?.textContent ?? undefined) : undefined
        },
    })
}
