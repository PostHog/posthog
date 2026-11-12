import { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_WITH_MEAN_METRIC from '~/mocks/fixtures/api/experiments/experiment_with_mean_metric.json'
import EXPOSURE_QUERY_RESULT from '~/mocks/fixtures/api/experiments/exposure_query_result.json'
import MEAN_METRIC_RESULT from '~/mocks/fixtures/api/experiments/mean_metric_result.json'
import { NodeKind } from '~/queries/schema/schema-general'

import type { RunningTimeTargetApi } from 'products/experiments/frontend/generated/api.schemas'

import { recalculationMocks, resultsByMetricType } from './recalculationMocks'

const EXPERIMENT_PATH = `/api/projects/:team_id/experiments/${EXPERIMENT_WITH_MEAN_METRIC.id}/`
const RECALCULATION = recalculationMocks(
    EXPERIMENT_WITH_MEAN_METRIC,
    resultsByMetricType(EXPERIMENT_WITH_MEAN_METRIC, { mean: MEAN_METRIC_RESULT })
)

// The fixture launched on 2025-05-20, so `mockDate` puts the run two weeks in, as each target response's outlook says.
const targetMocks = (target: RunningTimeTargetApi): Parameters<typeof mswDecorator>[0] => ({
    get: {
        ...RECALCULATION.get,
        [EXPERIMENT_PATH]: EXPERIMENT_WITH_MEAN_METRIC,
        [`${EXPERIMENT_PATH}running_time_target/`]: target,
        '/api/projects/:team_id/experiment_holdouts': [],
        '/api/projects/:team_id/experiment_saved_metrics/': [],
        [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_MEAN_METRIC.feature_flag.id}/`]:
            EXPERIMENT_WITH_MEAN_METRIC.feature_flag,
        [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_MEAN_METRIC.feature_flag.id}/status/`]: {},
        '/api/environments/:team_id/default_release_conditions/': [],
        '/api/projects/:team_id/experiments_config/': {},
        [`${EXPERIMENT_PATH}health/`]: { findings: [], checks: [] },
        '/api/projects/:team_id/property_definitions/seen_together': {},
    },
    post: {
        ...RECALCULATION.post,
        '/api/environments/:team_id/query/:kind': async ({ request }) => {
            const body = (await request.json()) as Record<string, any>
            return body.query.kind === NodeKind.ExperimentExposureQuery
                ? [200, EXPOSURE_QUERY_RESULT]
                : [200, { results: [] }]
        },
    },
    patch: { [EXPERIMENT_PATH]: EXPERIMENT_WITH_MEAN_METRIC },
})

const openRunningTimeSettings = async (): Promise<void> => {
    const settings = await waitFor(() => {
        const button = document.querySelector<HTMLElement>('[data-attr="experiment-running-time-config"]')
        if (!button) {
            throw new Error('The running time settings button has not rendered yet')
        }
        return button
    })
    await userEvent.click(settings)
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Experiments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-06-03',
        pageUrl: urls.experiment(EXPERIMENT_WITH_MEAN_METRIC.id),
    },
}
export default meta

type Story = StoryObj<{}>

// A target days away: the settings place it between the upcoming weeks.
export const ExperimentRunningTimeOnTrack: Story = {
    decorators: [
        mswDecorator(
            targetMocks({
                minimum_detectable_effect: 30,
                recommended_sample_size: 3000,
                current_sample_size: 2000,
                outlook: {
                    days_since_launch: 14,
                    exposures_per_day: 2000 / 14,
                    detectable_effect_now: 36.7,
                    upcoming_checkpoints: [
                        { weeks_since_launch: 4, detectable_effect: 26 },
                        { weeks_since_launch: 6, detectable_effect: 21.2 },
                        { weeks_since_launch: 8, detectable_effect: 18.4 },
                    ],
                    reachable_effect: 21.2,
                },
            })
        ),
    ],
    play: openRunningTimeSettings,
}

// A target months away: the header says what the experiment can detect by week 4, and the settings list the ways to
// finish sooner.
export const ExperimentRunningTimeOutOfReach: Story = {
    decorators: [
        mswDecorator(
            targetMocks({
                minimum_detectable_effect: 30,
                recommended_sample_size: 35556,
                current_sample_size: 2000,
                outlook: {
                    days_since_launch: 14,
                    exposures_per_day: 2000 / 14,
                    detectable_effect_now: 126.5,
                    upcoming_checkpoints: [
                        { weeks_since_launch: 4, detectable_effect: 89.4 },
                        { weeks_since_launch: 6, detectable_effect: 73 },
                        { weeks_since_launch: 8, detectable_effect: 63.2 },
                    ],
                    reachable_effect: 73,
                },
            })
        ),
    ],
    play: openRunningTimeSettings,
}
