import '@testing-library/jest-dom'

import { render, screen, waitFor } from '@testing-library/react'
import { router } from 'kea-router'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneLogic } from 'scenes/sceneLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, InsightShortId } from '~/types'

import { InsightAsScene } from './InsightAsScene'
import { insightSceneLogic } from './insightSceneLogic'

const INSIGHT_ID = '42' as InsightShortId
const DASHBOARD_ID = 33

const INSIGHT = {
    id: 42,
    short_id: INSIGHT_ID,
    name: 'Pageviews',
    description: '',
    dashboards: [DASHBOARD_ID],
    dashboard_tiles: [],
    query: {
        kind: 'InsightVizNode',
        source: { kind: 'TrendsQuery', series: [{ kind: 'EventsNode', event: '$pageview' }] },
    },
    // A cold cache key answers with no numbers
    result: null,
    saved: true,
    tags: [],
    order: null,
    deleted: false,
    created_at: '2024-01-01T00:00:00.000Z',
    created_by: null,
    is_sample: false,
    updated_at: '2024-01-01T00:00:00.000Z',
    last_modified_at: '2024-01-01T00:00:00.000Z',
    last_modified_by: null,
    last_refresh: null,
    user_access_level: AccessControlLevel.Editor,
}

describe('InsightAsScene', () => {
    let trendsQueries: number

    beforeEach(() => {
        trendsQueries = 0
        useMocks({
            get: {
                '/api/environments/:team_id/insights/': { results: [INSIGHT] },
                [`/api/environments/:team_id/dashboards/${DASHBOARD_ID}/`]: {
                    id: DASHBOARD_ID,
                    tiles: [],
                    filters: {},
                },
            },
            post: {
                '/api/environments/:team_id/query/TrendsQuery/': () => {
                    trendsQueries += 1
                    return [200, { results: [{ data: [1, 2, 3], days: ['2024-01-01'], label: '$pageview' }] }]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        sceneLogic.mount()
    })

    it('runs the query when an insight opened from a dashboard arrives without results', async () => {
        router.actions.push(
            `/insights/${INSIGHT_ID}?dashboard=${DASHBOARD_ID}&filters_override=${encodeURIComponent(
                JSON.stringify({ date_from: '-14d' })
            )}`
        )
        insightSceneLogic.mount()

        render(<InsightAsScene insightId={INSIGHT_ID} />)

        await waitFor(() => expect(trendsQueries).toBeGreaterThan(0))
        expect(screen.queryByText("Chart data didn't load")).not.toBeInTheDocument()
    })
})
