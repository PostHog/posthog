import { render, screen, waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { InsightViz } from './InsightViz'

const TRENDS_VIZ: InsightVizNode = {
    kind: NodeKind.InsightVizNode,
    source: {
        kind: NodeKind.TrendsQuery,
        series: [{ kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' }],
    },
} as InsightVizNode

describe('InsightViz error state', () => {
    // Two statuses, so a hardcoded value cannot pass in place of the real one
    it.each([
        { status: 500, expectedTitle: "PostHog couldn't complete this query" },
        { status: 503, expectedTitle: "This query couldn't run right now" },
    ])('classifies a $status failure', async ({ status, expectedTitle }) => {
        useMocks({
            post: { '/api/environments/:team_id/query/TrendsQuery/': () => [status, { detail: 'boom' }] },
        })
        initKeaTests()

        render(<InsightViz query={TRENDS_VIZ} setQuery={() => {}} readOnly />)

        await waitFor(() => {
            expect(screen.getByText(expectedTitle)).toBeTruthy()
        })
    })
})
