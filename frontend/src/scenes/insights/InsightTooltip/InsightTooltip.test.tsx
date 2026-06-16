import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { BreakdownFilter } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { InsightTooltip } from './InsightTooltip'
import { SeriesDatum } from './insightTooltipUtils'

describe('InsightTooltip', () => {
    beforeEach(() => {
        initKeaTests()
    })

    function renderTooltip(seriesData: SeriesDatum[], breakdownFilter: BreakdownFilter): ReturnType<typeof render> {
        return render(
            <Provider>
                <InsightTooltip
                    date="2026-06-15"
                    seriesData={seriesData}
                    breakdownFilter={breakdownFilter}
                    renderCount={(value) => `${value}%`}
                />
            </Provider>
        )
    }

    it('renders a value for every breakdown line in a funnel trend (not "–")', () => {
        const breakdownFilter: BreakdownFilter = { breakdown: '$browser', breakdown_type: 'event' }
        const seriesData: SeriesDatum[] = [
            { id: 0, dataIndex: 4, datasetIndex: 0, order: 0, breakdown_value: ['Chrome'], count: 16 },
            { id: 1, dataIndex: 4, datasetIndex: 1, order: 1, breakdown_value: ['Safari'], count: 17 },
            { id: 2, dataIndex: 4, datasetIndex: 2, order: 2, breakdown_value: ['Firefox'], count: 5 },
        ]

        renderTooltip(seriesData, breakdownFilter)

        expect(screen.getByText('16%')).toBeInTheDocument()
        expect(screen.getByText('17%')).toBeInTheDocument()
        expect(screen.getByText('5%')).toBeInTheDocument()
        expect(screen.queryByText('–')).not.toBeInTheDocument()
    })
})
