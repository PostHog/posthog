import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useLayoutEffect, useState } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'
import { teamLogic } from 'scenes/teamLogic'

import { FlagEvaluationsModeEnumApi } from '~/generated/core/api.schemas'
import { mswDecorator } from '~/mocks/browser'
import { InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { InsightModel } from '~/types'

import trendsLine from '../../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json'

const team = { ...MOCK_DEFAULT_TEAM, flag_evaluations_mode: FlagEvaluationsModeEnumApi.Number1 }

const fixture = trendsLine as unknown as Partial<InsightModel> & { query: InsightVizNode<TrendsQuery> }
const query: InsightVizNode<TrendsQuery> = {
    ...fixture.query,
    source: {
        ...fixture.query.source,
        series: [{ kind: NodeKind.EventsNode, event: '$feature_flag_called', name: '$feature_flag_called' }],
    },
}
const flagCallsInsight: Partial<InsightModel> = { ...fixture, query }

type Story = StoryObj<{}>
const meta: Meta = {
    title: 'Scenes-App/Insights/Flag Called Rebuild Banner',
    parameters: {
        layout: 'fullscreen',
        featureFlags: [FEATURE_FLAGS.FLAG_CALLED_REBUILD_BANNERS],
        testOptions: {
            snapshotBrowsers: ['chromium'],
            // Narrow enough that the banner text and its action wrap, as they do with the side panel open.
            viewport: { width: 900, height: 720 },
        },
        viewMode: 'story',
        mockDate: '2026-10-07T12:00:00Z',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/@current/': team,
                '/api/environments/:team_id/': team,
            },
            // The default handlers answer these with the mode 0 team, which would hide the banner after a write.
            patch: {
                '/api/environments/:team_id/add_product_intent/': team,
                '/api/environments/:team_id/': team,
            },
        }),
    ],
}
export default meta

const FlagCallsInsightScene = createInsightStory(flagCallsInsight) as unknown as () => JSX.Element

// The app context bootstraps the default team on mode 0, so the story loads the mode 1 team before the scene mounts.
function InsightOnFlagCallsStory(): JSX.Element | null {
    const { loadCurrentTeamSuccess } = useActions(teamLogic)
    const [ready, setReady] = useState(false)

    useLayoutEffect(() => {
        loadCurrentTeamSuccess(team)
        setReady(true)
    }, [loadCurrentTeamSuccess])

    return ready ? <FlagCallsInsightScene /> : null
}

export const InsightOnFlagCalls: Story = { render: () => <InsightOnFlagCallsStory /> }
