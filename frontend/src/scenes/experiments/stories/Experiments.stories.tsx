import { Meta, StoryFn } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_DRAFT from '~/mocks/fixtures/api/experiments/_experiment_draft.json'
import EXPERIMENT_WITH_LEGACY_FUNNELS_QUERY from '~/mocks/fixtures/api/experiments/experiment_with_funnels_query.json'
import EXPERIMENT_WITH_MULTIPLE_METRICS from '~/mocks/fixtures/api/experiments/experiment_with_multiple_metrics.json'
import EXPERIMENT_WITH_LEGACY_TRENDS_QUERY from '~/mocks/fixtures/api/experiments/experiment_with_trends_query.json'
import { toPaginatedResponse } from '~/mocks/handlers'

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
                '/api/projects/:team_id/experiments/': toPaginatedResponse([
                    EXPERIMENT_DRAFT,
                    EXPERIMENT_WITH_LEGACY_TRENDS_QUERY,
                    EXPERIMENT_WITH_LEGACY_FUNNELS_QUERY,
                    EXPERIMENT_WITH_MULTIPLE_METRICS,
                ]),
                '/api/projects/:team_id/experiment_holdouts': [],
                '/api/projects/:team_id/experiment_saved_metrics/': [],
            },
        }),
    ],
}
export default meta

export const Experiments: StoryFn = () => {
    useEffect(() => {
        router.actions.push(urls.experiments())
    }, [])
    return <App />
}
