import {
    getSeparatorTileThickness,
    separatorTileThicknessClassName,
    separatorTileToMarkdown,
} from './separatorTileUtils'

describe('separator tiles', () => {
    it.each(['thin', 'medium', 'thick'] as const)('round trips the %s thickness', (thickness) => {
        expect(getSeparatorTileThickness(separatorTileToMarkdown(thickness))).toEqual(thickness)
    })

    it('does not convert arbitrary text cards into separators', () => {
        expect(getSeparatorTileThickness('---')).toBeNull()
        expect(getSeparatorTileThickness('<hr />')).toBeNull()
    })

    it.each([
        ['thin', 'h-px'],
        ['medium', 'h-0.5'],
        ['thick', 'h-1'],
    ] as const)('uses the expected CSS class for %s lines', (thickness, className) => {
        expect(separatorTileThicknessClassName(thickness)).toEqual(className)
    })
})
