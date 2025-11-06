import { Meta, StoryObj } from '@storybook/react'

import { makeDelay } from 'lib/utils'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_WITH_MULTIPLE_METRICS from '~/mocks/fixtures/api/experiments/experiment_with_multiple_metrics.json'
import EXPOSURE_QUERY_RESULT from '~/mocks/fixtures/api/experiments/exposure_query_result.json'
import FUNNEL_METRIC_RESULT from '~/mocks/fixtures/api/experiments/funnel_metric_result.json'
import MEAN_METRIC_RESULT from '~/mocks/fixtures/api/experiments/mean_metric_result.json'
import RATIO_METRIC_RESULT from '~/mocks/fixtures/api/experiments/ratio_metric_result.json'
import {
    NodeKind,
    isExperimentFunnelMetric,
    isExperimentMeanMetric,
    isExperimentRatioMetric,
} from '~/queries/schema/schema-general'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Experiments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-01-27',
        pageUrl: urls.experiment(EXPERIMENT_WITH_MULTIPLE_METRICS.id),
    },
    decorators: [
        mswDecorator({
            get: {
                [`/api/projects/:team_id/experiments/${EXPERIMENT_WITH_MULTIPLE_METRICS.id}/`]:
                    EXPERIMENT_WITH_MULTIPLE_METRICS,
                [`/api/projects/:team_id/experiment_holdouts`]: [],
                [`/api/projects/:team_id/experiment_saved_metrics/`]: [],
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_MULTIPLE_METRICS.feature_flag.id}/`]: {},
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_MULTIPLE_METRICS.feature_flag.id}/status/`]:
                    {},
            },
            post: {
                '/api/environments/:team_id/query': (req, res, ctx) => {
                    const body = req.body as Record<string, any>

                    if (body.query.kind === NodeKind.ExperimentExposureQuery) {
                        return res(ctx.json(EXPOSURE_QUERY_RESULT))
                    }

                    if (isExperimentFunnelMetric(body.query.metric)) {
                        return res(ctx.json(FUNNEL_METRIC_RESULT))
                    } else if (isExperimentMeanMetric(body.query.metric)) {
                        return res(ctx.json(MEAN_METRIC_RESULT))
                    } else if (isExperimentRatioMetric(body.query.metric)) {
                        return res(ctx.json(RATIO_METRIC_RESULT))
                    }
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>

// Small delay to ensure charts render completely
export const ExperimentWithMultipleMetrics: Story = { play: makeDelay(500) }
