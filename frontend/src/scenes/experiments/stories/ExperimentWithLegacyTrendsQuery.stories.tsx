import { Meta, StoryFn } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_WITH_TRENDS_QUERY from '~/mocks/fixtures/api/experiments/experiment_with_trends_query.json'
import EXPOSURE_QUERY_RESULT from '~/mocks/fixtures/api/experiments/exposure_query_result.json'
import TRENDS_QUERY_RESULT from '~/mocks/fixtures/api/experiments/trends_query_result.json'
import { NodeKind } from '~/queries/schema/schema-general'

const meta: Meta = {
    title: 'Scenes-App/Experiments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-01-27',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/experiments/12/': EXPERIMENT_WITH_TRENDS_QUERY,
                '/api/projects/:team_id/experiment_holdouts': [],
                '/api/projects/:team_id/experiment_saved_metrics/': [],
                '/api/projects/:team_id/feature_flags/137/': {},
                '/api/projects/:team_id/feature_flags/137/status/': {},
            },
            post: {
                '/api/environments/:team_id/query': (req, res, ctx) => {
                    const body = req.body as Record<string, any>

                    if (body.query.kind === NodeKind.ExperimentExposureQuery) {
                        return res(ctx.json(EXPOSURE_QUERY_RESULT))
                    }

                    return res(ctx.json(TRENDS_QUERY_RESULT))
                },
            },
        }),
    ],
}
export default meta

export const ExperimentWithLegacyTrendsQuery: StoryFn = () => {
    useEffect(() => {
        router.actions.push(urls.experiment(EXPERIMENT_WITH_TRENDS_QUERY.id))
    }, [])
    return <App />
}
ExperimentWithLegacyTrendsQuery.play = async () => {
    // Add a small delay to ensure charts render completely
    await new Promise((resolve) => setTimeout(resolve, 500))
}
