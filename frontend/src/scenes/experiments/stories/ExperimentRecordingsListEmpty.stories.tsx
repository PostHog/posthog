import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { makeDelay } from 'lib/utils/async'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_WITH_FUNNEL_METRIC from '~/mocks/fixtures/api/experiments/experiment_with_funnel_metric.json'

// One story per empty reason: the copy is the feature, and a screenshot is the only way to check
// that each reason reads as its own answer. The default session_recordings handler returns an empty
// page, so every story here lands on the empty state.
const EXPERIMENT_PATH = `/api/projects/:team_id/experiments/${EXPERIMENT_WITH_FUNNEL_METRIC.id}/`
const SESSION_BUCKETS_PATH = `/api/projects/:team_id/experiments/${EXPERIMENT_WITH_FUNNEL_METRIC.id}/session_buckets/`

// `mockDate` below is 2025-06-01, and the mock team keeps recordings for 30 days. Each story sets
// the run window against those two so the tab resolves the reason the story is named for.
const experimentRun = (startDate: string | null, endDate: string | null): Record<string, unknown> => ({
    ...EXPERIMENT_WITH_FUNNEL_METRIC,
    start_date: startDate,
    end_date: endDate,
})

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Experiments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-06-01',
        pageUrl: urls.experiment(EXPERIMENT_WITH_FUNNEL_METRIC.id) + '?tab=recordings',
        testOptions: { waitForSelector: '[data-attr="experiment-recordings-empty-state"]' },
    },
    decorators: [
        mswDecorator({
            get: {
                [EXPERIMENT_PATH]: EXPERIMENT_WITH_FUNNEL_METRIC,
                '/api/environments/:team_id/experiments_config/': {},
                '/api/projects/:team_id/experiment_holdouts': { count: 0, results: [] },
                '/api/projects/:team_id/experiment_saved_metrics/': { count: 0, results: [] },
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_FUNNEL_METRIC.feature_flag.id}/`]:
                    EXPERIMENT_WITH_FUNNEL_METRIC.feature_flag,
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_FUNNEL_METRIC.feature_flag.id}/status/`]: {},
                '/api/environments/:team_id/default_release_conditions/': [],
                '/api/projects/:team_id/property_definitions/seen_together': {},
                '/api/projects/:team_id/vision/scanners/': { count: 0, results: [] },
            },
            post: {
                '/api/environments/:team_id/query/:kind': [200, { results: [] }],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

/** Replay is on, the run window is inside retention, and the filters still matched nothing. */
export const ExperimentRecordingsEmptyUnknownInWindow: Story = {}

export const ExperimentRecordingsEmptyTooEarly: Story = {
    decorators: [mswDecorator({ get: { [EXPERIMENT_PATH]: experimentRun('2025-05-30T09:00:00Z', null) } })],
}

export const ExperimentRecordingsEmptyEndedPastRetention: Story = {
    decorators: [
        mswDecorator({
            get: { [EXPERIMENT_PATH]: experimentRun('2025-01-10T09:00:00Z', '2025-04-01T09:00:00Z') },
        }),
    ],
}

export const ExperimentRecordingsEmptyReplayDisabled: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/': { ...MOCK_DEFAULT_TEAM, session_recording_opt_in: false },
                '/api/environments/@current/': { ...MOCK_DEFAULT_TEAM, session_recording_opt_in: false },
                '/api/projects/@current/': { ...MOCK_DEFAULT_TEAM, session_recording_opt_in: false },
            },
        }),
    ],
}

/** The two metric-filter reasons need the filter switched on, which only the menu can do. */
const pickFiredNone: Story['play'] = async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await makeDelay(700)()
    await userEvent.click(canvas.getByTestId('experiment-recordings-metric-filter'))
    await userEvent.click(await canvas.findByText('Fired none'))
    await makeDelay(700)()
}

export const ExperimentRecordingsEmptyMetricFilterMatchedNothing: Story = {
    decorators: [
        mswDecorator({
            post: {
                [SESSION_BUCKETS_PATH]: {
                    session_ids: [],
                    truncated: false,
                    considered_metrics: [{ metric_uuid: 'funnel', metric_name: 'Checkout funnel' }],
                    excluded_metrics: [],
                    filter_test_accounts: true,
                },
            },
        }),
    ],
    play: pickFiredNone,
}

export const ExperimentRecordingsEmptyMetricFilterFailed: Story = {
    decorators: [mswDecorator({ post: { [SESSION_BUCKETS_PATH]: [400, { detail: 'Could not resolve the filter' }] } })],
    play: pickFiredNone,
}
