import { Meta, StoryFn } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { TeamPublicType } from '~/types'

import { ToolbarLaunch } from './ToolbarLaunch'
import { FEATURE_FLAGS } from 'lib/constants'

const meta: Meta = {
    title: 'Scenes-Other/ToolbarLaunch',
    parameters: {
        layout: 'fullscreen',
        testOptions: {
            includeNavigationInSnapshot: true,
        },
        featureFlags: [FEATURE_FLAGS.WEB_EXPERIMENTS],
        viewMode: 'story',
        mockDate: '2024-01-01',
    },
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:environment_id/query/': () => [
                    200,
                    {
                        results: [
                            ['https://posthog.com', 150],
                            ['https://app.posthog.com', 100],
                            ['https://docs.posthog.com', 75],
                        ],
                    },
                ],
            },
        }),
    ],
}
export default meta

const Template: StoryFn = () => {
    useEffect(() => {
        router.actions.push(urls.dashboards())
    }, [])

    return <ToolbarLaunch />
}

export const Default = Template.bind({})

export const NoUrlsTemplate: StoryFn = () => {
    const { currentTeam } = useValues(teamLogic)
    const { loadCurrentTeamSuccess } = useActions(teamLogic)

    useEffect(() => {
        const team = { ...currentTeam, app_urls: [] }
        loadCurrentTeamSuccess(team as TeamPublicType)
    }, []) // eslint-disable-line react-hooks/exhaustive-deps

    return <Template />
}

export const NoSuggestionsTemplate: StoryFn = () => {
    useStorybookMocks({
        post: { '/api/environments/:environment_id/query/': () => [200, { results: [] }] },
    })

    return <Template />
}

export const EmptyStateTemplate: StoryFn = () => {
    const { currentTeam } = useValues(teamLogic)
    const { loadCurrentTeamSuccess } = useActions(teamLogic)

    useEffect(() => {
        const team = { ...currentTeam, app_urls: [] }
        loadCurrentTeamSuccess(team as TeamPublicType)
    }, []) // eslint-disable-line react-hooks/exhaustive-deps

    useStorybookMocks({
        post: { '/api/environments/:environment_id/query/': () => [200, { results: [] }] },
    })

    return <Template />
}
