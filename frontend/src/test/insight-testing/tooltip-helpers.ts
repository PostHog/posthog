export interface TooltipAccessor {
    element: HTMLElement
    row(label: string): string | undefined
}

export function createTooltipAccessor(element: HTMLElement): TooltipAccessor {
    return {
        element,

        row(label: string): string | undefined {
            const rows = element.querySelectorAll('tr')
            for (let i = 0; i < rows.length; i++) {
                const row = rows[i]
                if (row.textContent?.includes(label)) {
                    const cell = row.querySelector('.datum-counts-column')
                    return cell?.textContent ?? undefined
                }
            }
            return undefined
        },
    }
}
