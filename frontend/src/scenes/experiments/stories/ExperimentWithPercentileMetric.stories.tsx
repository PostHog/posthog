import { Meta, StoryObj } from '@storybook/react'

import { makeDelay } from 'lib/utils/async'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_WITH_QUANTILE_METRIC from '~/mocks/fixtures/api/experiments/experiment_with_quantile_metric.json'
import QUANTILE_EXPOSURE_QUERY_RESULT from '~/mocks/fixtures/api/experiments/quantile_exposure_query_result.json'
import QUANTILE_METRIC_RESULT from '~/mocks/fixtures/api/experiments/quantile_metric_result.json'
import { NodeKind } from '~/queries/schema/schema-general'

import { recalculationMocks, resultsByMetricType } from './recalculationMocks'

const RECALCULATION = recalculationMocks(
    EXPERIMENT_WITH_QUANTILE_METRIC,
    resultsByMetricType(EXPERIMENT_WITH_QUANTILE_METRIC, { quantile: QUANTILE_METRIC_RESULT })
)

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Experiments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-01-27',
        pageUrl: urls.experiment(EXPERIMENT_WITH_QUANTILE_METRIC.id),
    },
    decorators: [
        mswDecorator({
            get: {
                ...RECALCULATION.get,
                [`/api/projects/:team_id/experiments/${EXPERIMENT_WITH_QUANTILE_METRIC.id}/`]:
                    EXPERIMENT_WITH_QUANTILE_METRIC,
                [`/api/projects/:team_id/experiment_holdouts`]: [],
                [`/api/projects/:team_id/experiment_saved_metrics/`]: [],
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_QUANTILE_METRIC.feature_flag.id}/`]:
                    EXPERIMENT_WITH_QUANTILE_METRIC.feature_flag,
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_QUANTILE_METRIC.feature_flag.id}/status/`]: {},
                [`/api/environments/:team_id/default_release_conditions/`]: [],
                // Answered so the scene does not raise failure toasts over the results
                '/api/projects/:team_id/experiments_config/': {},
                '/api/projects/:team_id/property_definitions/seen_together': {},
                '/api/projects/:team_id/experiments/:id/running_time_target/': {},
            },
            post: {
                ...RECALCULATION.post,
                '/api/projects/:team_id/file_system/home_folder/': { id: 'example-home', path: 'Users/Example' },
                // Exposures still load through experimentLogic; metric results come from the recalculation run.
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    return body.query.kind === NodeKind.ExperimentExposureQuery
                        ? [200, QUANTILE_EXPOSURE_QUERY_RESULT]
                        : [404]
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

// Small delay to ensure charts render completely
export const ExperimentWithPercentileMetric: Story = { play: makeDelay(500) }
