import { Meta, StoryFn } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_DRAFT from '~/mocks/fixtures/api/experiments/_experiment_draft.json'

const meta: Meta = {
    title: 'Scenes-App/Experiments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-01-27',
        featureFlags: ['experiments-new-query-runner'],
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

export const DraftExperiment: StoryFn = () => {
    useEffect(() => {
        router.actions.push(urls.experiment(EXPERIMENT_DRAFT.id))
    }, [])
    return <App />
}
