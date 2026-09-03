export type SeparatorTileThickness = 'thin' | 'medium' | 'thick'

const SEPARATOR_TILE_PATTERN = /^<hr data-dashboard-separator-thickness="(thin|medium|thick)" \/>$/

export const DEFAULT_SEPARATOR_TILE_THICKNESS: SeparatorTileThickness = 'thin'

export function separatorTileToMarkdown(thickness: SeparatorTileThickness): string {
    return `<hr data-dashboard-separator-thickness="${thickness}" />`
}

export function getSeparatorTileThickness(markdown: string | null | undefined): SeparatorTileThickness | null {
    const match = markdown?.trim().match(SEPARATOR_TILE_PATTERN)
    return (match?.[1] as SeparatorTileThickness | undefined) ?? null
}

export function separatorTileThicknessClassName(thickness: SeparatorTileThickness): string {
    if (thickness === 'thick') {
        return 'h-1'
    }
    if (thickness === 'medium') {
        return 'h-0.5'
    }
    return 'h-px'
}
