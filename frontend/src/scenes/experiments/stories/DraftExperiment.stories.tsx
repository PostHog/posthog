import { Meta, StoryObj } from '@storybook/react'
import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_DRAFT from '~/mocks/fixtures/api/experiments/_experiment_draft.json'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Experiments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-01-27',
        featureFlags: [FEATURE_FLAGS.EXPERIMENTS_NEW_QUERY_RUNNER],
        pageUrl: urls.experiment(EXPERIMENT_DRAFT.id),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/experiments/20/': EXPERIMENT_DRAFT,
                '/api/projects/:team_id/experiment_holdouts': [],
                '/api/projects/:team_id/experiment_saved_metrics/': [],
                '/api/projects/:team_id/feature_flags/24/': {},
                '/api/projects/:team_id/feature_flags/24/status/': {},
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>
export const DraftExperiment: Story = {}
