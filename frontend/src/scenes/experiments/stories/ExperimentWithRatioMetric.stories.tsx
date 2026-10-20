import { Meta, StoryObj } from '@storybook/react'

import { makeDelay } from 'lib/utils/async'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_WITH_RATIO_METRIC from '~/mocks/fixtures/api/experiments/experiment_with_ratio_metric.json'
import EXPOSURE_QUERY_RESULT from '~/mocks/fixtures/api/experiments/exposure_query_result.json'
import RATIO_METRIC_RESULT from '~/mocks/fixtures/api/experiments/ratio_metric_result.json'
import { NodeKind } from '~/queries/schema/schema-general'

import { recalculationMocks, resultsByMetricType } from './recalculationMocks'

const RECALCULATION = recalculationMocks(
    EXPERIMENT_WITH_RATIO_METRIC,
    resultsByMetricType(EXPERIMENT_WITH_RATIO_METRIC, { ratio: RATIO_METRIC_RESULT })
)

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Experiments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-01-27',
        pageUrl: urls.experiment(EXPERIMENT_WITH_RATIO_METRIC.id),
    },
    decorators: [
        mswDecorator({
            get: {
                ...RECALCULATION.get,
                [`/api/projects/:team_id/experiments/${EXPERIMENT_WITH_RATIO_METRIC.id}/`]:
                    EXPERIMENT_WITH_RATIO_METRIC,
                [`/api/projects/:team_id/experiment_holdouts`]: [],
                [`/api/projects/:team_id/experiment_saved_metrics/`]: [],
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_RATIO_METRIC.feature_flag.id}/`]: {},
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_RATIO_METRIC.feature_flag.id}/status/`]: {},
                [`/api/environments/:team_id/default_release_conditions/`]: [],
            },
            post: {
                ...RECALCULATION.post,
                // Exposures still load through experimentLogic; metric results come from the recalculation run.
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    return body.query.kind === NodeKind.ExperimentExposureQuery ? [200, EXPOSURE_QUERY_RESULT] : [404]
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

// Small delay to ensure charts render completely
export const ExperimentWithRatioMetric: Story = { play: makeDelay(500) }
