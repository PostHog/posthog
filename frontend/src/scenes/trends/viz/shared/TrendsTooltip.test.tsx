import { render } from '@testing-library/react'

import type { TooltipContext } from 'lib/hog-charts'

import { TrendsTooltip } from './TrendsTooltip'
import type { TrendsSeriesMeta } from './trendsSeriesMeta'

const insightTooltipMock = jest.fn(() => null)
jest.mock('scenes/insights/InsightTooltip/InsightTooltip', () => ({
    InsightTooltip: (props: Record<string, unknown>) => insightTooltipMock(props),
}))
jest.mock('scenes/insights/InsightTooltip/insightTooltipUtils', () => ({
    getDatumTitle: () => '',
    SeriesDatum: undefined,
}))

function buildContext(overrides: Partial<TooltipContext<TrendsSeriesMeta>> = {}): TooltipContext<TrendsSeriesMeta> {
    return {
        label: 'Chrome',
        dataIndex: 0,
        position: { x: 0, y: 0 },
        canvasBounds: { x: 0, y: 0, width: 0, height: 0, top: 0, right: 0, bottom: 0, left: 0 },
        isPinned: false,
        seriesData: [
            {
                series: {
                    key: 'chrome',
                    label: 'Chrome',
                    data: [100],
                    color: '#ff0000',
                    meta: { breakdown_value: 'Chrome' },
                },
                value: 100,
                color: '#ff0000',
            },
        ],
        ...overrides,
    } as TooltipContext<TrendsSeriesMeta>
}

describe('TrendsTooltip', () => {
    beforeEach(() => insightTooltipMock.mockClear())

    it.each([
        { name: 'forwards showHeader=false', showHeader: false, expected: false },
        { name: 'forwards undefined so InsightTooltip default applies', showHeader: undefined, expected: undefined },
        { name: 'forwards showHeader=true', showHeader: true, expected: true },
    ])('$name', ({ showHeader, expected }) => {
        render(<TrendsTooltip context={buildContext()} showHeader={showHeader} />)
        const props = insightTooltipMock.mock.calls.at(-1)?.[0] as { showHeader?: boolean }
        expect(props.showHeader).toBe(expected)
    })
})
