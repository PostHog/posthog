export interface TooltipRow {
    element: HTMLElement
    expectValue(value: string): void
}

export interface TooltipAccessor {
    element: HTMLElement
    row(label: string): TooltipRow | undefined
}

export function createTooltipAccessor(element: HTMLElement): TooltipAccessor {
    return {
        element,

        row(label: string): TooltipRow | undefined {
            const rows = element.querySelectorAll('tr')
            for (let i = 0; i < rows.length; i++) {
                const row = rows[i]
                if (row.textContent?.includes(label)) {
                    return {
                        element: row as HTMLElement,
                        expectValue(value: string) {
                            const cell = row.querySelector('.datum-counts-column')
                            if (!cell) {
                                throw new Error(`Row "${label}" has no counts cell`)
                            }
                            expect(cell.textContent).toContain(value)
                        },
                    }
                }
            }
            return undefined
        },
    }
}
