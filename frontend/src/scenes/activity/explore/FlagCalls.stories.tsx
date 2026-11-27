import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { combineUrl } from 'kea-router'

import { App } from 'scenes/App'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { FlagEvaluationsModeEnumApi } from '~/generated/core/api.schemas'
import { mswDecorator } from '~/mocks/browser'
import { ActivityTab } from '~/types'

import flagCallsQuery from './__mocks__/flagCallsQuery.json'
import { getDefaultFlagCallsSceneQuery } from './flagCallsSceneLogic'

const FLAG_CALLS_TEAM = {
    ...MOCK_DEFAULT_TEAM,
    flag_evaluations_mode: FlagEvaluationsModeEnumApi.Number2,
    flag_calls_only_in_flag_evaluations: true,
}

function flagCallsMocks(queryResponse: Record<string, any>): ReturnType<typeof mswDecorator> {
    return mswDecorator({
        get: {
            '/api/projects/:team_id/column_configurations/': { results: [] },
        },
        // Other logics run a HogQLQuery on load. Rows in its answer make them update the team, which drops the override.
        post: { '/api/environments/:team_id/query/EventsQuery': queryResponse },
    })
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Flag calls',
    decorators: [
        (Story) => {
            teamLogic.mount()
            teamLogic.actions.loadCurrentTeamSuccess(FLAG_CALLS_TEAM)
            return <Story />
        },
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-28',
        pageUrl: urls.activity(ActivityTab.ExploreFlagCalls),
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj<{}>

export const FlagCalls: Story = {
    decorators: [flagCallsMocks(flagCallsQuery)],
}

export const Empty: Story = {
    decorators: [flagCallsMocks({ results: [] })],
}

const pastRetentionQuery = getDefaultFlagCallsSceneQuery()
export const PastRetention: Story = {
    decorators: [flagCallsMocks(flagCallsQuery)],
    parameters: {
        pageUrl: combineUrl(
            urls.activity(ActivityTab.ExploreFlagCalls),
            {},
            {
                q: {
                    ...pastRetentionQuery,
                    source: { ...pastRetentionQuery.source, after: '-180d' },
                },
            }
        ).url,
    },
}
