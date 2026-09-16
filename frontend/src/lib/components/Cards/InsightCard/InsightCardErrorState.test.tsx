import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'
import posthog from 'posthog-js'

import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { DashboardPlacement, InsightShortId, QueryBasedInsightModel } from '~/types'

import { InsightCard } from './InsightCard'

const INSIGHT = {
    short_id: 'short1' as InsightShortId,
    id: 1,
    name: 'A failing insight',
    query: { kind: NodeKind.InsightVizNode, source: { kind: NodeKind.TrendsQuery, series: [] } },
    result: null,
} as unknown as QueryBasedInsightModel

// Export is the only placement that renders the visualization in jsdom, because the card
// otherwise waits for the tile to come into view.
describe('InsightCard error states', () => {
    let captureSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        captureSpy = jest.spyOn(posthog, 'capture')
        captureSpy.mockClear()
    })

    afterEach(() => {
        cleanup()
    })

    it('reports the query context of an error that is not an ApiError', () => {
        render(
            <InsightCard
                insight={INSIGHT}
                placement={DashboardPlacement.Export}
                queryId="query-1"
                apiErrored
                apiError={new Error('Something went wrong')}
            />
        )

        const shownCalls = captureSpy.mock.calls.filter((call) => call[0] === 'insight error message shown')
        expect(shownCalls).toHaveLength(1)
        expect(shownCalls[0][1]).toMatchObject({
            query_kind: 'TrendsQuery',
            query_id: 'query-1',
        })
    })
})
