import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_WITH_FUNNEL_METRIC from '~/mocks/fixtures/api/experiments/experiment_with_funnel_metric.json'
import EXPOSURE_QUERY_RESULT from '~/mocks/fixtures/api/experiments/exposure_query_result.json'
import FUNNELS_METRIC_RESULT from '~/mocks/fixtures/api/experiments/funnel_metric_result.json'
import { NodeKind } from '~/queries/schema/schema-general'

const EXPERIMENT_WITH_LONG_FLAG_KEY = {
    ...EXPERIMENT_WITH_FUNNEL_METRIC,
    feature_flag: {
        ...EXPERIMENT_WITH_FUNNEL_METRIC.feature_flag,
        key: 'checkout-redesign-v3-sticky-summary-and-express-pay-buttons-for-returning-customers',
    },
}

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
                [`/api/projects/:team_id/experiments/${EXPERIMENT_WITH_LONG_FLAG_KEY.id}/`]:
                    EXPERIMENT_WITH_LONG_FLAG_KEY,
                [`/api/projects/:team_id/experiment_holdouts`]: [],
                [`/api/projects/:team_id/experiment_saved_metrics/`]: [],
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_LONG_FLAG_KEY.feature_flag.id}/`]: {},
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_LONG_FLAG_KEY.feature_flag.id}/status/`]: {},
                [`/api/environments/:team_id/default_release_conditions/`]: [],
            },
            post: {
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>

                    if (body.query.kind === NodeKind.ExperimentExposureQuery) {
                        return [200, EXPOSURE_QUERY_RESULT]
                    }

                    return [200, FUNNELS_METRIC_RESULT]
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const ExperimentWithLongFlagKey: Story = {}
