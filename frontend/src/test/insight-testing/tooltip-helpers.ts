export interface TooltipAccessor {
    element: HTMLElement
    /** Header text — typically the hovered date (e.g. "Wednesday, 12 Jun (UTC)"). */
    title(): string
    /** Value cell text for the row whose datum column contains `label`. */
    row(label: string): string | undefined
    /** Ordered list of row datum labels (skips the header row). */
    rows(): string[]
}

export function createTooltipAccessor(element: HTMLElement): TooltipAccessor {
    return {
        element,

        title(): string {
            // The InsightTooltip's first column carries the date/header text. Its <th>
            // doesn't have a stable class hook in either tooltip variant, so we just
            // pick off the first <th> in the table head.
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
    }
}
