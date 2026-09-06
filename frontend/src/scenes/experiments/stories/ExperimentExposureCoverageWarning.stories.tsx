import { Meta, StoryObj } from '@storybook/react'

import { makeDelay } from 'lib/utils/async'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_WITH_MEAN_METRIC from '~/mocks/fixtures/api/experiments/experiment_with_mean_metric.json'
import EXPOSURE_QUERY_RESULT from '~/mocks/fixtures/api/experiments/exposure_query_result.json'
import MEAN_METRIC_RESULT from '~/mocks/fixtures/api/experiments/mean_metric_result.json'
import { NodeKind } from '~/queries/schema/schema-general'

const EXPOSURE_QUERY_RESULT_WITH_COVERAGE_GAP = {
    ...EXPOSURE_QUERY_RESULT,
    exposure_coverage: {
        evaluated_entities: 5043,
        errored_entities: 4712,
        errored_percentage: 48.3,
        error_reasons: { timeout: 4102, connection_error: 610 },
    },
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Experiments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-01-27',
        pageUrl: urls.experiment(EXPERIMENT_WITH_MEAN_METRIC.id),
    },
    decorators: [
        mswDecorator({
            get: {
                [`/api/projects/:team_id/experiments/${EXPERIMENT_WITH_MEAN_METRIC.id}/`]: EXPERIMENT_WITH_MEAN_METRIC,
                [`/api/projects/:team_id/experiment_holdouts`]: [],
                [`/api/projects/:team_id/experiment_saved_metrics/`]: [],
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_MEAN_METRIC.feature_flag.id}/`]: {},
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_MEAN_METRIC.feature_flag.id}/status/`]: {},
                [`/api/environments/:team_id/default_release_conditions/`]: [],
            },
            post: {
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>

                    if (body.query.kind === NodeKind.ExperimentExposureQuery) {
                        return [200, EXPOSURE_QUERY_RESULT_WITH_COVERAGE_GAP]
                    }

                    return [200, MEAN_METRIC_RESULT]
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const ExperimentExposureCoverageWarning: Story = { play: makeDelay(500) }
