import { metricsPreviewP95 } from './metricsAlertPreview'

describe('metricsPreviewP95', () => {
    const row = (data: number[]): { key: string; label: string; data: number[] } => ({ key: 'k', label: 'l', data })

    it.each([
        ['no points', [], null],
        ['only gaps', [row([NaN, NaN])], null],
        ['all zero', [row([0, 0])], 0],
        ['interpolates across every series and skips gaps', [row([1, 2, NaN, 3, 4, 5]), row([6, 7, 8, 9, 10])], 9.55],
        ['rounds up so the threshold never sits below the P95', [row([12_341, 12_342, 12_343])], 12_400],
        ['rounds negative values towards zero', [row([-1_234.5, -1_234.6])], -1_230],
    ])('%s', (_, rows, expected) => {
        expect(metricsPreviewP95({ rows, labels: [] })).toBe(expected)
    })
})
