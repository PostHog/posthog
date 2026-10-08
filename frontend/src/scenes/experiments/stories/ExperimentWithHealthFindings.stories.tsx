import { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { makeDelay } from 'lib/utils/async'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_WITH_MEAN_METRIC from '~/mocks/fixtures/api/experiments/experiment_with_mean_metric.json'
import EXPOSURE_QUERY_RESULT from '~/mocks/fixtures/api/experiments/exposure_query_result.json'
import MEAN_METRIC_RESULT from '~/mocks/fixtures/api/experiments/mean_metric_result.json'
import { NodeKind } from '~/queries/schema/schema-general'

const EXPERIMENT_WITH_HEALTH_FINDINGS = {
    ...EXPERIMENT_WITH_MEAN_METRIC,
    health: {
        findings: [
            {
                code: 'flag_off_while_running',
                subcode: 'running_but_no_rollout',
                severity: 'warning',
                title: 'The experiment is running, but no new users are being exposed',
                detail: 'The linked feature flag has a 0% rollout, so no new users are being exposed. Users exposed earlier are still included in the results. End the experiment with a conclusion, or increase the rollout percentage to expose users.',
                evidence: {},
                actions: ['open_feature_flag'],
                diagnostic_ref: 'A5',
            },
        ],
    },
}

const EXPOSURES_WITH_BIAS_RISK = {
    ...EXPOSURE_QUERY_RESULT,
    sample_ratio_mismatch: { expected: { control: 1000, 'test-1': 1000, 'test-2': 1000 }, p_value: 0.0001 },
    bias_risk: { multiple_variant_percentage: 4.2 },
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
                [`/api/projects/:team_id/experiments/${EXPERIMENT_WITH_MEAN_METRIC.id}/`]:
                    EXPERIMENT_WITH_HEALTH_FINDINGS,
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
                        return [200, EXPOSURES_WITH_BIAS_RISK]
                    }

                    return [200, MEAN_METRIC_RESULT]
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

// One finding open and two closed, so both row states are in one picture.
export const ExperimentWithHealthFindings: Story = {
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await makeDelay(500)()
        const [firstWhy] = await canvas.findAllByText('Why?', {}, { timeout: 5000 })
        await userEvent.click(firstWhy)
        await makeDelay(500)()
    },
}
