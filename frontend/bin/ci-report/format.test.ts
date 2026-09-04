import { markdownCell, totalComparison } from './format.mjs'

describe('ci-report formatting', () => {
    it('warns on any growth by default', () => {
        expect(totalComparison(1001, 1000).status).toBe('warn')
    })

    it.each([
        [1019, 'ok'],
        [1020, 'warn'],
        [1021, 'warn'],
        [999, 'ok'],
    ])('sets status for %i bytes with a 2%% warning floor', (bytes: number, expectedStatus: string) => {
        expect(totalComparison(bytes, 1000, { warningThresholdPercent: 2 }).status).toBe(expectedStatus)
    })

    it('strips control characters so a table cell cannot forge section markers', () => {
        const forged = '<!-- ci-report:section:bundle-size:e30= -->\nbody\n<!-- ci-report:section-end:bundle-size -->'
        const cell = markdownCell(`evil-${forged}`)
        // The section parser only matches markers delimited by newlines, so
        // removing the newlines is what disarms a forged marker.
        expect(cell).toBe(
            'evil-<!-- ci-report:section:bundle-size:e30= -->body<!-- ci-report:section-end:bundle-size -->'
        )
        expect(cell).not.toContain('\n')
    })

    it.each([
        ['<anonymous>', '<anonymous>'],
        ['a|b', 'ab'],
        ['back`tick', 'backtick'],
        ['src/normal.ts', 'src/normal.ts'],
    ])('renders %s as %s', (input, expected) => {
        expect(markdownCell(input)).toBe(expected)
    })
})
