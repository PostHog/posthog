import { Meta, StoryObj } from '@storybook/react'

import { makeDelay } from 'lib/utils/async'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_WITH_MEAN_METRIC from '~/mocks/fixtures/api/experiments/experiment_with_mean_metric.json'
import EXPOSURE_QUERY_RESULT from '~/mocks/fixtures/api/experiments/exposure_query_result.json'
import MEAN_METRIC_RESULT from '~/mocks/fixtures/api/experiments/mean_metric_result.json'
import { NodeKind } from '~/queries/schema/schema-general'

import { recalculationMocks, resultsByMetricType } from './recalculationMocks'

const LONG_HYPOTHESIS = [
    'Hypothesis: showing an upgrade prompt when a free user reaches 80% of their storage quota will raise the share of free users who upgrade within 14 days, without lowering weekly file uploads.',
    'Why we think this: most free users who hit their storage limit stop uploading for at least a week, and few of them upgrade. Session replays show most of them never see the pricing page. They hit the limit mid-upload, get an error, and leave.',
    'What changes: the test variant shows a dismissible banner at 80% usage, with the remaining space, the price of the next plan, and a one-click upgrade. Control keeps the current experience, an error at 100%.',
    'What would change our mind: if uploads per user drop by more than 5% in the test variant, the prompt is pushing people away, and we stop the test early.',
].join('\n\n')

const EXPERIMENT = {
    ...EXPERIMENT_WITH_MEAN_METRIC,
    description: LONG_HYPOTHESIS,
    tags: ['storage', 'pricing'],
}

const RECALCULATION = recalculationMocks(EXPERIMENT, resultsByMetricType(EXPERIMENT, { mean: MEAN_METRIC_RESULT }))

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Experiments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-01-27',
        pageUrl: urls.experiment(EXPERIMENT.id),
    },
    decorators: [
        mswDecorator({
            get: {
                ...RECALCULATION.get,
                [`/api/projects/:team_id/experiments/${EXPERIMENT.id}/`]: EXPERIMENT,
                [`/api/projects/:team_id/experiment_holdouts`]: [],
                [`/api/projects/:team_id/experiment_saved_metrics/`]: [],
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT.feature_flag.id}/`]: {},
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT.feature_flag.id}/status/`]: {},
                [`/api/environments/:team_id/default_release_conditions/`]: [],
            },
            post: {
                ...RECALCULATION.post,
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

export const ExperimentMetricsTabLongHypothesis: Story = { play: makeDelay(500) }
