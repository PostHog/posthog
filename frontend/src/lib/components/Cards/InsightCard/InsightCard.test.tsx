import { render } from '@testing-library/react'

import { DashboardPlacement, QueryBasedInsightModel } from '~/types'

import { InsightCard } from './InsightCard'

const makeInsight = (): QueryBasedInsightModel =>
    ({
        id: 1,
        short_id: 'shortid',
        name: 'Test insight',
        query: { kind: 'HogQLQuery', query: 'SELECT 1' },
    }) as QueryBasedInsightModel

describe('InsightCard', () => {
    it('renders eight handles when showResizeHandles=true', () => {
        const { container } = render(
            <InsightCard insight={makeInsight()} placement={DashboardPlacement.Dashboard} showResizeHandles={true} />
        )

        const handles = container.querySelectorAll('.handle')
        expect(handles.length).toBe(8)
    })
})
