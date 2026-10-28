import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { makeDelay } from 'lib/utils/async'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_WITH_FUNNEL_METRIC from '~/mocks/fixtures/api/experiments/experiment_with_funnel_metric.json'

const scanners = [
    {
        id: '0192aaaa-0000-7000-8000-000000000001',
        name: 'experiment-funnel-metric (#15)',
        scanner_type: 'experiment',
        observations_this_month: 128,
    },
    {
        id: '0192bbbb-0000-7000-8000-000000000002',
        name: 'Signup drop-off',
        scanner_type: 'summarizer',
        observations_this_month: 12,
    },
]

const recordingsTabMocks = (watching: typeof scanners): ReturnType<typeof mswDecorator> =>
    mswDecorator({
        get: {
            [`/api/projects/:team_id/experiments/${EXPERIMENT_WITH_FUNNEL_METRIC.id}/`]: EXPERIMENT_WITH_FUNNEL_METRIC,
            '/api/projects/:team_id/experiment_holdouts': [],
            '/api/projects/:team_id/experiment_saved_metrics/': [],
            [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_FUNNEL_METRIC.feature_flag.id}/`]: {},
            [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_FUNNEL_METRIC.feature_flag.id}/status/`]: {},
            '/api/environments/:team_id/default_release_conditions/': [],
            '/api/projects/:team_id/vision/scanners/': { count: watching.length, results: watching },
        },
        post: {
            '/api/environments/:team_id/query/:kind': [200, { results: [] }],
        },
    })

// A launched experiment's Recordings tab, where Replay vision offers an experiment scanner, or lists
// the scanners already watching the experiment.
const meta: Meta = {
    component: App,
    title: 'Scenes-App/Experiments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-06-01',
        pageUrl: urls.experiment(EXPERIMENT_WITH_FUNNEL_METRIC.id) + '?tab=recordings',
        featureFlags: [FEATURE_FLAGS.VISION_EXPERIMENT_SCANNER],
        testOptions: { waitForSelector: '[data-attr="experiment-recordings-tab"]' },
    },
}
export default meta

type Story = StoryObj<{}>

export const ExperimentReplayScannerBacklink: Story = {
    decorators: [recordingsTabMocks(scanners)],
    play: makeDelay(700),
}

export const ExperimentReplayScannerCrossSell: Story = {
    decorators: [recordingsTabMocks([])],
    play: makeDelay(700),
}
