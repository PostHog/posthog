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

// One story per empty reason, plus the too-early shelf that a cap bound: the copy is the feature,
// and a screenshot is the only way to check that they read as different answers.
const DELTAS_PATH = `/api/projects/:team_id/experiments/${EXPERIMENT_WITH_FUNNEL_METRIC.id}/session_event_deltas/`

// What the shelf holds besides its reason, and which of them the copy reads. Defaults describe a
// comparison big enough to have found an ordinary difference; a story that needs the other answer
// says so.
interface ShelfOptions {
    sessionsTruncated?: boolean
    /** Below 0.5 is what the backend reports 'underpowered' on, so the two must agree in a fixture. */
    detectableShare?: number | null
    /** Overrides on the experiment itself: an end date, a paused status, or a launch date close enough to be young. */
    experiment?: Record<string, unknown>
    /** Scanners already watching this experiment. One of them replaces every cross-sell with a back-link. */
    scanners?: { id: string; name: string; scanner_type: string; observations_this_month: number }[]
}

// Typed as the generated response so a new required field on the serializer breaks the typecheck here.
const emptyShelf = (
    emptyReason: ExperimentWatchEmptyReasonEnumApi,
    variantPersons: number[],
    { sessionsTruncated = false, detectableShare = 0.92 }: ShelfOptions
): ExperimentSessionEventDeltaResponseApi => ({
    cards: [],
    variants: [
        { key: 'control', persons: variantPersons[0], sessions: Math.round(variantPersons[0] * 1.4) },
        { key: 'test-1', persons: variantPersons[1], sessions: Math.round(variantPersons[1] * 1.3) },
        { key: 'test-2', persons: variantPersons[2], sessions: Math.round(variantPersons[2] * 1.4) },
    ],
    multiple_variant_persons: 0,
    multiple_variant_handling: ExperimentWatchMultipleVariantHandlingEnumApi.Exclude,
    metric_events: ['checkout_started', 'purchase'],
    date_from: '2025-05-30T09:00:00Z',
    date_to: '2025-06-01T09:00:00Z',
    filter_test_accounts: true,
    used_exposure_fallback: false,
    sessions_truncated: sessionsTruncated,
    events_truncated: false,
    min_variant_persons: 50,
    max_card_recordings: 20,
    dropped_duplicate_cards: 0,
    // True for the unsessioned case too: those variants are below the floor, only the reason differs.
    too_early:
        emptyReason === ExperimentWatchEmptyReasonEnumApi.TooEarly ||
        emptyReason === ExperimentWatchEmptyReasonEnumApi.NoSessionLinkedExposures,
    empty_reason: emptyReason,
    // Null wherever nothing was compared, which is the same pair of reasons `too_early` covers.
    detectable_share:
        emptyReason === ExperimentWatchEmptyReasonEnumApi.TooEarly ||
        emptyReason === ExperimentWatchEmptyReasonEnumApi.NoSessionLinkedExposures
            ? null
            : detectableShare,
})

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Experiments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-06-01',
        pageUrl: urls.experiment(EXPERIMENT_WITH_FUNNEL_METRIC.id) + '?tab=recordings',
        // The vision entry point too, because which empty state carries the scanner offer and
        // which does not is half of what this story set checks.
        featureFlags: [FEATURE_FLAGS.EXPERIMENT_BEHAVIOR_COMPARISON, FEATURE_FLAGS.VISION_ENTRYPOINT_EXPERIMENTS],
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

const shelfStory = (
    emptyReason: ExperimentWatchEmptyReasonEnumApi,
    variantPersons: number[],
    options: ShelfOptions = {}
): Story => ({
    decorators: [
        mswDecorator({
            get: {
                [`/api/projects/:team_id/experiments/${EXPERIMENT_WITH_FUNNEL_METRIC.id}/`]: {
                    ...EXPERIMENT_WITH_FUNNEL_METRIC,
                    ...options.experiment,
                },
                '/api/projects/:team_id/vision/scanners/': {
                    count: options.scanners?.length ?? 0,
                    results: options.scanners ?? [],
                },
            },
            post: { [DELTAS_PATH]: emptyShelf(emptyReason, variantPersons, options) },
        }),
    ],
    play: openTheShelf,
})

export const ExperimentWatchShelfTooEarly: Story = shelfStory(ExperimentWatchEmptyReasonEnumApi.TooEarly, [12, 12, 12])
// A cap bound the comparison, so the banner must not promise that waiting alone fills it.
export const ExperimentWatchShelfTooEarlyTruncated: Story = shelfStory(
    ExperimentWatchEmptyReasonEnumApi.TooEarly,
    [1900, 3, 0],
    { sessionsTruncated: true }
)
// The one empty state that carries the tailored scanner offer.
export const ExperimentWatchShelfNoSeparation: Story = shelfStory(
    ExperimentWatchEmptyReasonEnumApi.NoSeparation,
    [2400, 2400, 2400]
)
// A scanner already watches this experiment, so the reader has Replay vision and the pitch is noise.
export const ExperimentWatchShelfNoSeparationWithScanner: Story = shelfStory(
    ExperimentWatchEmptyReasonEnumApi.NoSeparation,
    [2400, 2400, 2400],
    {
        scanners: [
            { id: 'scanner-1', name: 'Checkout confusion', scanner_type: 'classifier', observations_this_month: 42 },
        ],
    }
)
// Small enough that a doubling could not have carded, so the copy sizes the comparison instead of
// reporting that the variants behaved the same. No scanner offer: the answer here is to wait.
export const ExperimentWatchShelfUnderpowered: Story = shelfStory(
    ExperimentWatchEmptyReasonEnumApi.Underpowered,
    [190, 190, 190],
    { detectableShare: 0.21 }
)
// A cap bound the comparison, so waiting adds nobody and "check back" would be a false promise.
export const ExperimentWatchShelfUnderpoweredTruncated: Story = shelfStory(
    ExperimentWatchEmptyReasonEnumApi.Underpowered,
    [190, 190, 190],
    { detectableShare: 0.21, sessionsTruncated: true }
)
// The string that matters most: an ended run reads as a clean negative result today, and is not one.
export const ExperimentWatchShelfUnderpoweredEnded: Story = shelfStory(
    ExperimentWatchEmptyReasonEnumApi.Underpowered,
    [190, 190, 190],
    { detectableShare: 0.21, experiment: { end_date: '2025-05-31T09:00:00Z' } }
)
// Started two days before the mocked date: a young run leads with its age, so an empty shelf reads
// as normal this early rather than as something being wrong.
export const ExperimentWatchShelfUnderpoweredYoung: Story = shelfStory(
    ExperimentWatchEmptyReasonEnumApi.Underpowered,
    [190, 190, 190],
    { detectableShare: 0.21, experiment: { start_date: '2025-05-29T09:00:00Z' } }
)
// The other state that leads with its age, where the reader has not even reached a comparison yet.
export const ExperimentWatchShelfTooEarlyYoung: Story = shelfStory(
    ExperimentWatchEmptyReasonEnumApi.TooEarly,
    [12, 12, 12],
    { experiment: { start_date: '2025-05-29T09:00:00Z' } }
)
// Paused, so it has not ended and nobody new is being exposed either. Both of these states end
// with a promise of more people everywhere else, and a paused run is where that promise is empty.
export const ExperimentWatchShelfUnderpoweredPaused: Story = shelfStory(
    ExperimentWatchEmptyReasonEnumApi.Underpowered,
    [190, 190, 190],
    { detectableShare: 0.21, experiment: { status: 'paused' } }
)
export const ExperimentWatchShelfTooEarlyPaused: Story = shelfStory(
    ExperimentWatchEmptyReasonEnumApi.TooEarly,
    [12, 12, 12],
    { experiment: { status: 'paused' } }
)
export const ExperimentWatchShelfNoRecordings: Story = shelfStory(
    ExperimentWatchEmptyReasonEnumApi.NoRecordings,
    [2400, 2400, 2400]
)
export const ExperimentWatchShelfNoSessionLinkedExposures: Story = shelfStory(
    ExperimentWatchEmptyReasonEnumApi.NoSessionLinkedExposures,
    [0, 0, 0]
)

// A 400 is the backend refusing a comparison this experiment cannot have, so the shelf states it
// and offers no retry. Shot at two widths because the line sits under the filter row, where a long
// refusal is what runs out of room first.
const REFUSAL_DETAIL = 'This experiment has only one variant, so there is nothing to compare it against.'

const refusedStory = (width: number): Story => ({
    parameters: { testOptions: { viewport: { width, height: 1000 } } },
    decorators: [mswDecorator({ post: { [DELTAS_PATH]: [400, { detail: REFUSAL_DETAIL }] } })],
    play: openTheShelf,
})

export const ExperimentWatchShelfRefused: Story = refusedStory(1300)
export const ExperimentWatchShelfRefusedNarrow: Story = refusedStory(800)
