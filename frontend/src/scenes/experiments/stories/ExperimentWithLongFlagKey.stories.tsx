import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_WITH_FUNNEL_METRIC from '~/mocks/fixtures/api/experiments/experiment_with_funnel_metric.json'
import EXPOSURE_QUERY_RESULT from '~/mocks/fixtures/api/experiments/exposure_query_result.json'
import FUNNELS_METRIC_RESULT from '~/mocks/fixtures/api/experiments/funnel_metric_result.json'
import { NodeKind } from '~/queries/schema/schema-general'

import { recalculationMocks, resultsByMetricType } from './recalculationMocks'

const EXPERIMENT_WITH_LONG_FLAG_KEY = {
    ...EXPERIMENT_WITH_FUNNEL_METRIC,
    feature_flag: {
        ...EXPERIMENT_WITH_FUNNEL_METRIC.feature_flag,
        key: 'checkout-redesign-v3-sticky-summary-and-express-pay-buttons-for-returning-customers',
    },
}

const RECALCULATION = recalculationMocks(
    EXPERIMENT_WITH_LONG_FLAG_KEY,
    resultsByMetricType(EXPERIMENT_WITH_LONG_FLAG_KEY, { funnel: FUNNELS_METRIC_RESULT })
)

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Experiments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-01-27',
        pageUrl: urls.experiment(EXPERIMENT_WITH_LONG_FLAG_KEY.id),
        testOptions: {
            // The funnel chart only renders once the metric result AND the exposure query have
            // both resolved. The loader wait covers the metric table alone, so wait for the chart
            // itself to avoid snapshotting before it appears.
            waitForSelector: '[data-attr="experiment-funnel-chart"]',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                ...RECALCULATION.get,
                [`/api/projects/:team_id/experiments/${EXPERIMENT_WITH_LONG_FLAG_KEY.id}/`]:
                    EXPERIMENT_WITH_LONG_FLAG_KEY,
                [`/api/projects/:team_id/experiment_holdouts`]: [],
                [`/api/projects/:team_id/experiment_saved_metrics/`]: [],
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_LONG_FLAG_KEY.feature_flag.id}/`]: {},
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_LONG_FLAG_KEY.feature_flag.id}/status/`]: {},
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

export const ExperimentWithLongFlagKey: Story = {}
