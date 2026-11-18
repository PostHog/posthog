import { Meta, StoryObj } from '@storybook/react'

import { makeDelay } from 'lib/utils/async'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_WITH_MULTIPLE_METRICS_REORDERED from '~/mocks/fixtures/api/experiments/experiment_with_multiple_metrics_reordered.json'
import EXPOSURE_QUERY_RESULT from '~/mocks/fixtures/api/experiments/exposure_query_result.json'
import FUNNEL_METRIC_RESULT from '~/mocks/fixtures/api/experiments/funnel_metric_result.json'
import MEAN_METRIC_RESULT from '~/mocks/fixtures/api/experiments/mean_metric_result.json'
import RATIO_METRIC_RESULT from '~/mocks/fixtures/api/experiments/ratio_metric_result.json'
import { NodeKind } from '~/queries/schema/schema-general'

import { recalculationMocks, resultsByMetricType } from './recalculationMocks'

const RECALCULATION = recalculationMocks(
    EXPERIMENT_WITH_MULTIPLE_METRICS_REORDERED,
    resultsByMetricType(EXPERIMENT_WITH_MULTIPLE_METRICS_REORDERED, {
        mean: MEAN_METRIC_RESULT,
        funnel: FUNNEL_METRIC_RESULT,
        ratio: RATIO_METRIC_RESULT,
    })
)

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Experiments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-01-27',
        pageUrl: urls.experiment(EXPERIMENT_WITH_MULTIPLE_METRICS_REORDERED.id),
    },
    decorators: [
        mswDecorator({
            get: {
                ...RECALCULATION.get,
                [`/api/projects/:team_id/experiments/${EXPERIMENT_WITH_MULTIPLE_METRICS_REORDERED.id}/`]:
                    EXPERIMENT_WITH_MULTIPLE_METRICS_REORDERED,
                [`/api/projects/:team_id/experiment_holdouts`]: [],
                [`/api/projects/:team_id/experiment_saved_metrics/`]: [],
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_MULTIPLE_METRICS_REORDERED.feature_flag.id}/`]:
                    {},
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_MULTIPLE_METRICS_REORDERED.feature_flag.id}/status/`]:
                    {},
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
export const ExperimentWithMultipleMetricsReordered: Story = { play: makeDelay(500) }
