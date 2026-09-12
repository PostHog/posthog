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

// A p-value between 0.001 and 0.05 is evidence that the split is off without being
// conclusive, so the panel must not show the green check for it.
const BORDERLINE_SRM_EXPOSURE_QUERY_RESULT = {
    ...EXPOSURE_QUERY_RESULT,
    sample_ratio_mismatch: {
        expected: { control: 1000.0, 'test-1': 1000.0, 'test-2': 1000.0 },
        p_value: 0.003,
        daily: { date: '2025-05-31', p_value: 0.02 },
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
                        return [200, EXPOSURE_QUERY_RESULT]
                    }

                    return [200, MEAN_METRIC_RESULT]
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

// The cumulative exposures chart only mounts once the panel is open, so no default-render story
// reaches it.
const openExposuresPanel: Story['play'] = async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await makeDelay(500)()
    await userEvent.click(await canvas.findByText('Exposures'))
    await makeDelay(500)()
}

export const ExperimentExposuresExpanded: Story = {
    play: openExposuresPanel,
}

export const ExperimentExposuresBorderlineSrm: Story = {
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>

                    if (body.query.kind === NodeKind.ExperimentExposureQuery) {
                        return [200, BORDERLINE_SRM_EXPOSURE_QUERY_RESULT]
                    }

                    return [200, MEAN_METRIC_RESULT]
                },
            },
        }),
    ],
    play: openExposuresPanel,
}
