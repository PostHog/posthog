import { Meta, StoryObj } from '@storybook/react'
import { FEATURE_FLAGS } from 'lib/constants'
import { makeDelay } from 'lib/utils'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_METRIC_RESULT_WITH_ASYMMETRIC_INTERVALS from '~/mocks/fixtures/api/experiments/_experiment_metric_result_asymmetric_interval.json'
import EXPERIMENT_WITH_ASYMMETRIC_INTERVALS from '~/mocks/fixtures/api/experiments/_experiment_with_asymmetric_credible_interval.json'
import EXPOSURE_QUERY_RESULT from '~/mocks/fixtures/api/experiments/exposure_query_result.json'
import { NodeKind } from '~/queries/schema/schema-general'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Experiments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-01-27',
        featureFlags: [FEATURE_FLAGS.EXPERIMENTS_NEW_QUERY_RUNNER],
        pageUrl: urls.experiment(EXPERIMENT_WITH_ASYMMETRIC_INTERVALS.id),
    },
    decorators: [
        mswDecorator({
            get: {
                [`/api/projects/:team_id/experiments/${EXPERIMENT_WITH_ASYMMETRIC_INTERVALS.id}/`]:
                    EXPERIMENT_WITH_ASYMMETRIC_INTERVALS,
                [`/api/projects/:team_id/experiment_holdouts`]: [],
                [`/api/projects/:team_id/experiment_saved_metrics/`]: [],
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_ASYMMETRIC_INTERVALS.feature_flag.id}/`]: {},
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_ASYMMETRIC_INTERVALS.feature_flag.id}/status/`]:
                    {},
            },
            post: {
                '/api/environments/:team_id/query': (req, res, ctx) => {
                    const body = req.body as Record<string, any>

                    if (body.query.kind === NodeKind.ExperimentExposureQuery) {
                        return res(ctx.json(EXPOSURE_QUERY_RESULT))
                    }

                    return res(ctx.json(EXPERIMENT_METRIC_RESULT_WITH_ASYMMETRIC_INTERVALS))
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>

// Small delay to ensure charts render completely
export const ExperimentAsymmetricIntervals: Story = { play: makeDelay(500) }
