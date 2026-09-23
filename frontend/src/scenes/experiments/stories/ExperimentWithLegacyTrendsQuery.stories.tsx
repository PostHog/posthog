import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_WITH_TRENDS_QUERY from '~/mocks/fixtures/api/experiments/experiment_with_trends_query.json'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Experiments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-01-27',
        pageUrl: urls.experiment(EXPERIMENT_WITH_TRENDS_QUERY.id),
    },
    decorators: [
        mswDecorator({
            get: {
                [`/api/projects/:team_id/experiments/${EXPERIMENT_WITH_TRENDS_QUERY.id}/`]:
                    EXPERIMENT_WITH_TRENDS_QUERY,
                [`/api/projects/:team_id/experiment_holdouts`]: [],
                [`/api/projects/:team_id/experiment_saved_metrics/`]: [],
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_TRENDS_QUERY.feature_flag.id}/`]: {},
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_TRENDS_QUERY.feature_flag.id}/status/`]: {},
                [`/api/environments/:team_id/default_release_conditions/`]: [],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const ExperimentWithLegacyTrendsQuery: Story = {}
