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

import { recalculationMocks, resultsByMetricType } from './recalculationMocks'

const RECALCULATION = recalculationMocks(
    EXPERIMENT_WITH_MEAN_METRIC,
    resultsByMetricType(EXPERIMENT_WITH_MEAN_METRIC, { mean: MEAN_METRIC_RESULT })
)

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
                ...RECALCULATION.get,
                [`/api/projects/:team_id/experiments/${EXPERIMENT_WITH_MEAN_METRIC.id}/`]: EXPERIMENT_WITH_MEAN_METRIC,
                [`/api/projects/:team_id/experiment_holdouts`]: [],
                [`/api/projects/:team_id/experiment_saved_metrics/`]: [],
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_MEAN_METRIC.feature_flag.id}/`]: {},
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_MEAN_METRIC.feature_flag.id}/status/`]: {},
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

// The cumulative exposures chart only mounts once the panel is open, so no default-render story
// reaches it.
export const ExperimentExposuresExpanded: Story = {
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await makeDelay(500)()
        await userEvent.click(await canvas.findByText('Exposures'))
        await makeDelay(500)()
    },
}
