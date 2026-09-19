import '@testing-library/jest-dom'

import { cleanup, render, waitFor } from '@testing-library/react'
import { BindLogic } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { BREAKDOWN_NULL_STRING_LABEL } from 'scenes/insights/utils'

import { NodeKind, TrendsQueryResponse } from '~/queries/schema/schema-general'
import { buildTrendsQuery, renderInsight } from '~/test/insight-testing'
import { INSIGHT_TEST_ID } from '~/test/insight-testing/render-insight'
import { InsightLogicProps } from '~/types'

import { trendsDataLogic } from 'products/product_analytics/frontend/insights/trends/trendsDataLogic'
import { IndexedTrendResult } from 'products/product_analytics/frontend/insights/trends/types'

import { InsightLegendRow } from './InsightLegendRow'

const nullBucketResponse = {
    results: [
        {
            action: { id: '$pageview', type: 'events', name: '$pageview', order: 0 },
            order: 0,
            label: '$pageview',
            count: 3,
            data: [1, 2],
            labels: ['Day 1', 'Day 2'],
            days: ['2024-01-01', '2024-01-02'],
            breakdown_value: BREAKDOWN_NULL_STRING_LABEL,
        },
    ],
} as unknown as TrendsQueryResponse

describe('InsightLegendRow', () => {
    afterEach(() => {
        cleanup()
    })

    // Regression: the tooltip wrapped InsightLabel, which takes no DOM props, so nothing on the row
    // carried the hover handlers and the explanation could not be opened by any input.
    it('gives the null breakdown explanation an element to hover', async () => {
        renderInsight({
            query: buildTrendsQuery({ breakdownFilter: { breakdown: '$pathname', breakdown_type: 'event' } }),
            mocks: {
                mockResponses: [
                    { match: (query) => query.kind === NodeKind.TrendsQuery, response: nullBucketResponse },
                ],
            },
        })

        const props: InsightLogicProps = { dashboardItemId: INSIGHT_TEST_ID }
        await waitFor(() => {
            expect((trendsDataLogic(props).values.indexedResults as IndexedTrendResult[]).length).toBe(1)
        })

        const { container } = render(
            <BindLogic logic={insightLogic} props={props}>
                <InsightLegendRow item={(trendsDataLogic(props).values.indexedResults as IndexedTrendResult[])[0]} />
            </BindLogic>
        )

        const trigger = container.querySelector('[data-base-ui-tooltip-trigger]')
        expect(trigger).not.toBeNull()
        expect(trigger).toContainElement(container.querySelector('[data-attr="insight-label"]'))
    })
})
