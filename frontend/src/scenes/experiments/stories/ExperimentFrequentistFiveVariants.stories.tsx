import { Meta, StoryFn } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_FREQUENTIST_FIVE_VARIANTS from '~/mocks/fixtures/api/experiments/experiment_frequentist_five_variants.json'
import FUNNEL_METRIC_RESULT from '~/mocks/fixtures/api/experiments/experiment_frequentist_five_variants_funnel_metric_result.json'
import MEAN_METRIC_RESULT from '~/mocks/fixtures/api/experiments/experiment_frequentist_five_variants_mean_metric_result.json'
import EXPOSURE_QUERY_RESULT from '~/mocks/fixtures/api/experiments/exposure_query_result.json'
import { NodeKind } from '~/queries/schema/schema-general'
import { App } from '~/scenes/App'
import { urls } from '~/scenes/urls'

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
                '/api/projects/:team_id/experiments/20/': EXPERIMENT_FREQUENTIST_FIVE_VARIANTS,
                '/api/projects/:team_id/experiment_holdouts': [],
                '/api/projects/:team_id/experiment_saved_metrics/': [],
                '/api/projects/:team_id/feature_flags/322/': {},
                '/api/projects/:team_id/feature_flags/322/status/': {},
            },
            post: {
                '/api/environments/:team_id/query': (req, res, ctx) => {
                    const body = req.body as Record<string, any>

                    if (body.query.kind === NodeKind.ExperimentExposureQuery) {
                        return res(ctx.json(EXPOSURE_QUERY_RESULT))
                    }

                    if (body.query.metric.metric_type === 'funnel') {
                        return res(ctx.json(FUNNEL_METRIC_RESULT))
                    } else if (body.query.metric.metric_type === 'mean') {
                        return res(ctx.json(MEAN_METRIC_RESULT))
                    }
                },
            },
        }),
    ],
}
export default meta

export const ExperimentFrequentistFiveVariants: StoryFn = () => {
    useEffect(() => {
        router.actions.push(urls.experiment(EXPERIMENT_FREQUENTIST_FIVE_VARIANTS.id))
    }, [])
    return <App />
}
ExperimentFrequentistFiveVariants.play = async () => {
    // Add a small delay to ensure charts render completely
    await new Promise((resolve) => setTimeout(resolve, 500))
}
