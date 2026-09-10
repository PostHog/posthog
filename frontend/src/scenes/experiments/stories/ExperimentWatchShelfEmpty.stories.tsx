import { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { makeDelay } from 'lib/utils/async'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_WITH_FUNNEL_METRIC from '~/mocks/fixtures/api/experiments/experiment_with_funnel_metric.json'

import {
    type ExperimentSessionEventDeltaResponseApi,
    ExperimentWatchEmptyReasonEnumApi,
    ExperimentWatchMultipleVariantHandlingEnumApi,
} from 'products/experiments/frontend/generated/api.schemas'

// One story per empty reason: the copy is the feature, and a screenshot is the only way to check
// that the four read as different answers.
const DELTAS_PATH = `/api/projects/:team_id/experiments/${EXPERIMENT_WITH_FUNNEL_METRIC.id}/session_event_deltas/`

// Typed as the generated response so a new required field on the serializer breaks the typecheck here.
const emptyShelf = (
    emptyReason: ExperimentWatchEmptyReasonEnumApi,
    variantPersons: number
): ExperimentSessionEventDeltaResponseApi => ({
    cards: [],
    variants: [
        { key: 'control', persons: variantPersons, sessions: Math.round(variantPersons * 1.4) },
        { key: 'test-1', persons: variantPersons, sessions: Math.round(variantPersons * 1.3) },
        { key: 'test-2', persons: variantPersons, sessions: Math.round(variantPersons * 1.4) },
    ],
    multiple_variant_persons: 0,
    multiple_variant_handling: ExperimentWatchMultipleVariantHandlingEnumApi.Exclude,
    metric_events: ['checkout_started', 'purchase'],
    date_from: '2025-05-30T09:00:00Z',
    date_to: '2025-06-01T09:00:00Z',
    filter_test_accounts: true,
    used_exposure_fallback: false,
    sessions_truncated: false,
    events_truncated: false,
    min_variant_persons: 50,
    max_card_recordings: 20,
    dropped_duplicate_cards: 0,
    // True for the unsessioned case too: those variants are below the floor, only the reason differs.
    too_early:
        emptyReason === ExperimentWatchEmptyReasonEnumApi.TooEarly ||
        emptyReason === ExperimentWatchEmptyReasonEnumApi.NoSessionLinkedExposures,
    empty_reason: emptyReason,
})

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Experiments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-06-01',
        pageUrl: urls.experiment(EXPERIMENT_WITH_FUNNEL_METRIC.id) + '?tab=recordings',
        featureFlags: [FEATURE_FLAGS.EXPERIMENT_BEHAVIOR_COMPARISON],
        testOptions: { waitForSelector: '[data-attr="experiment-recordings-tab"]' },
    },
    decorators: [
        mswDecorator({
            get: {
                [`/api/projects/:team_id/experiments/${EXPERIMENT_WITH_FUNNEL_METRIC.id}/`]:
                    EXPERIMENT_WITH_FUNNEL_METRIC,
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

const openTheShelf: Story['play'] = async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await makeDelay(700)()
    await userEvent.click(await canvas.findByText('What to watch'))
    await makeDelay(500)()
}

const shelfStory = (emptyReason: ExperimentWatchEmptyReasonEnumApi, variantPersons: number): Story => ({
    decorators: [mswDecorator({ post: { [DELTAS_PATH]: emptyShelf(emptyReason, variantPersons) } })],
    play: openTheShelf,
})

export const ExperimentWatchShelfTooEarly: Story = shelfStory(ExperimentWatchEmptyReasonEnumApi.TooEarly, 12)
export const ExperimentWatchShelfNoSeparation: Story = shelfStory(ExperimentWatchEmptyReasonEnumApi.NoSeparation, 2400)
export const ExperimentWatchShelfNoRecordings: Story = shelfStory(ExperimentWatchEmptyReasonEnumApi.NoRecordings, 2400)
export const ExperimentWatchShelfNoSessionLinkedExposures: Story = shelfStory(
    ExperimentWatchEmptyReasonEnumApi.NoSessionLinkedExposures,
    0
)
