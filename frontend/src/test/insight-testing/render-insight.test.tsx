import { cleanup } from '@testing-library/react'

import { breakdown, renderInsightPage, series, waitForChart } from './index'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

describe('renderInsightPage', () => {
    afterEach(() => {
        cleanup()
    })

    it.skip('breakdown naps by hedgehogs', async () => {
        renderInsightPage()
        await waitForChart()

        await series.select('Napped')
        await breakdown.set('hedgehog')

        const chart = await waitForChart()
        expect(chart.seriesNames).toEqual(['Spike', 'Bramble', 'Thistle', 'Conker', 'Prickles'])

        expect(chart.value('Spike', 'Thu')).toBe(4) // Spike had 4 naps on thursday
        expect(chart.series('Bramble').data).toEqual([0, 0, 1, 1, 0]) // Bramble had 1 nap on wednesday and thursday

        expect(chart.type).toBe('line')
        expect(chart.labels).toEqual(['Mon', 'Tue', 'Wed', 'Thu', 'Fri'])
    })
})
