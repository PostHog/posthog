import { Meta, StoryFn } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_METRIC_RESULT_WITH_ASYMMETRIC_INTERVALS from '~/mocks/fixtures/api/experiments/_experiment_metric_result_asymmetric_interval.json'
import EXPERIMENT_WITH_ASYMMETRIC_INTERVALS from '~/mocks/fixtures/api/experiments/_experiment_with_asymmetric_credible_interval.json'
import EXPOSURE_QUERY_RESULT from '~/mocks/fixtures/api/experiments/exposure_query_result.json'
import { NodeKind } from '~/queries/schema/schema-general'

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
                '/api/projects/:team_id/experiments/68/': EXPERIMENT_WITH_ASYMMETRIC_INTERVALS,
                '/api/projects/:team_id/experiment_holdouts': [],
                '/api/projects/:team_id/experiment_saved_metrics/': [],
                '/api/projects/997/feature_flags/163/': {},
                '/api/projects/997/feature_flags/163/status/': {},
            },
            post: {
                '/api/environments/:team_id/query': (req, res, ctx) => {
                    const body = req.body as Record<string, any>

                    if (body.query.kind === NodeKind.ExperimentExposureQuery) {
                        return res(ctx.json(EXPOSURE_QUERY_RESULT))
                    }

                    return res(ctx.json(EXPERIMENT_METRIC_RESULT_WITH_ASYMMETRIC_INTERVALS))
                },
            },
        }),
    ],
}
export default meta

export const ExperimentAsymmetricIntervals: StoryFn = () => {
    useEffect(() => {
        router.actions.push(urls.experiment(EXPERIMENT_WITH_ASYMMETRIC_INTERVALS.id))
    }, [])
    return <App />
}
ExperimentAsymmetricIntervals.play = async () => {
    // Add a small delay to ensure charts render completely
    await new Promise((resolve) => setTimeout(resolve, 500))
}
