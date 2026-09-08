import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import {
    DEFAULT_RECORDING_FILTERS,
    SessionRecordingPlaylistLogicProps,
    sessionRecordingsPlaylistLogic,
} from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { Experiment, FilterLogicalOperator, TeamType } from '~/types'

import {
    experimentsInSessionExposureRetrieve,
    experimentsSessionBucketsCreate,
} from 'products/experiments/frontend/generated/api'

import { ExperimentRecordingsListEmptyState } from './ExperimentRecordingsListEmptyState'
import { ExperimentReplayListEmptyReason, experimentReplayTabLogic } from './experimentReplayTabLogic'

jest.mock('lib/utils/product-intents', () => ({
    addProductIntentForCrossSell: jest.fn().mockResolvedValue(null),
}))

jest.mock('products/experiments/frontend/generated/api', () => ({
    experimentsInSessionExposureRetrieve: jest.fn(),
    experimentsSessionContextsCreate: jest.fn().mockResolvedValue({ results: [] }),
    experimentsSessionBucketsCreate: jest.fn(),
    experimentsSessionEventDeltasCreate: jest.fn().mockResolvedValue(null),
}))

jest.mock('products/replay_vision/frontend/generated/api', () => ({
    visionScannersList: jest.fn().mockResolvedValue({ results: [] }),
}))

// Run windows are read against today, so a fixed date would start naming a different reason as it
// aged. Counted in hours so a run in a zone with daylight saving still lands a whole number of days.
const daysAgo = (days: number): string =>
    dayjs()
        .subtract(days * 24, 'hour')
        .toISOString()

const EXPERIMENT = {
    id: 42,
    feature_flag_key: 'my-flag',
    start_date: daysAgo(10),
    end_date: null,
    metrics: [],
    metrics_secondary: [],
    feature_flag: {
        filters: {
            multivariate: {
                variants: [
                    { key: 'control', rollout_percentage: 50 },
                    { key: 'test', rollout_percentage: 50 },
                ],
            },
        },
    },
} as unknown as Experiment

// Every action the empty state can offer, so a case can state its whole set and an extra one fails.
// A LemonBanner action renders twice, once per width, so presence is counted rather than queried.
const ACTION_ATTRS = [
    'experiment-recordings-empty-replay-settings',
    'experiment-recordings-empty-retention-docs',
    'experiment-recordings-empty-ad-blocker-docs',
    'experiment-recordings-empty-retry-metric-filter',
    'experiment-recordings-empty-clear-filters',
    'experiment-recordings-empty-show-all-variants',
    'experiment-recordings-empty-all-sessions',
]

interface ReasonCase {
    reason: ExperimentReplayListEmptyReason
    /** One per case: the tab logic is keyed per experiment, and each case mounts its own. */
    experimentId: number
    experiment: Partial<Experiment>
    team?: Partial<TeamType>
    setup?: (logic: ReturnType<typeof experimentReplayTabLogic.build>) => void
    /** The part of the copy that only this reason says. */
    copy: string
    /** In `ACTION_ATTRS` order. */
    actions: string[]
}

// The team's retention period is the mock default of 30 days, which the run windows are set against.
const REASON_CASES: ReasonCase[] = [
    {
        reason: ExperimentReplayListEmptyReason.ReplayDisabled,
        experimentId: 201,
        experiment: {},
        team: { session_recording_opt_in: false },
        copy: 'Session replay is off for this project',
        actions: ['experiment-recordings-empty-replay-settings'],
    },
    {
        reason: ExperimentReplayListEmptyReason.NotLaunched,
        experimentId: 202,
        experiment: { start_date: null, end_date: null },
        copy: 'Launch the experiment to see recordings of participants.',
        actions: [],
    },
    {
        reason: ExperimentReplayListEmptyReason.TooEarly,
        experimentId: 203,
        experiment: { start_date: daysAgo(1), end_date: null },
        copy: 'The experiment started 1 day ago',
        actions: [],
    },
    {
        reason: ExperimentReplayListEmptyReason.EndedPastRetention,
        experimentId: 204,
        experiment: { start_date: daysAgo(200), end_date: daysAgo(60) },
        copy: 'This project keeps recordings for 30 days',
        actions: ['experiment-recordings-empty-retention-docs'],
    },
    {
        reason: ExperimentReplayListEmptyReason.MetricFilterMatchedNothing,
        experimentId: 205,
        experiment: { start_date: daysAgo(10), end_date: null },
        setup: (logic) => {
            ;(experimentsSessionBucketsCreate as jest.Mock).mockResolvedValue({
                session_ids: [],
                truncated: false,
                considered_metrics: [],
                excluded_metrics: [],
                filter_test_accounts: true,
            })
            logic.actions.setMetricFilterMode('no_metric_activity')
        },
        copy: 'No recordings matched the metric filter.',
        actions: [],
    },
    {
        reason: ExperimentReplayListEmptyReason.MetricFilterFailed,
        experimentId: 206,
        experiment: { start_date: daysAgo(10), end_date: null },
        setup: (logic) => {
            ;(experimentsSessionBucketsCreate as jest.Mock).mockRejectedValue({ detail: 'refused' })
            logic.actions.setMetricFilterMode('no_metric_activity')
        },
        copy: 'The metric filter could not be loaded',
        actions: ['experiment-recordings-empty-retry-metric-filter'],
    },
    {
        reason: ExperimentReplayListEmptyReason.FiltersNarrowed,
        experimentId: 212,
        experiment: { start_date: daysAgo(10), end_date: null },
        setup: (logic) =>
            logic.actions.playlistFiltersChanged({
                ...logic.values.recordingsFilters,
                filter_group: {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: FilterLogicalOperator.And,
                            values: [{ id: '$pageview', name: '$pageview', type: 'events', order: 0 }],
                        },
                    ],
                },
            }),
        copy: 'No recordings match the filters added above',
        actions: ['experiment-recordings-empty-clear-filters'],
    },
    {
        reason: ExperimentReplayListEmptyReason.UnknownInWindow,
        experimentId: 207,
        experiment: { start_date: daysAgo(10), end_date: daysAgo(2) },
        copy: 'A session can be missing for a few reasons',
        actions: ['experiment-recordings-empty-retention-docs', 'experiment-recordings-empty-ad-blocker-docs'],
    },
    {
        reason: ExperimentReplayListEmptyReason.VariantHasNone,
        experimentId: 210,
        experiment: { start_date: daysAgo(10), end_date: daysAgo(2) },
        setup: (logic) => logic.actions.setSelectedVariantKey('test'),
        copy: 'No recordings for the test variant',
        actions: ['experiment-recordings-empty-show-all-variants'],
    },
    {
        reason: ExperimentReplayListEmptyReason.InSessionHasNone,
        experimentId: 211,
        experiment: { start_date: daysAgo(10), end_date: daysAgo(2) },
        setup: (logic) => logic.actions.setExposureScope('in_session'),
        copy: 'No recordings of the sessions the exposure happened in',
        actions: ['experiment-recordings-empty-all-sessions'],
    },
]

describe('ExperimentRecordingsListEmptyState', () => {
    // The tab always scopes its playlist, so the empty state always renders under a scoped logic.
    const playlistProps: SessionRecordingPlaylistLogicProps = {
        logicKey: 'experiment-empty-state-test',
        updateSearchParams: false,
        filters: { ...DEFAULT_RECORDING_FILTERS, date_from: '-30d' },
    }
    let playlistLogic: ReturnType<typeof sessionRecordingsPlaylistLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/session_recordings': { results: [], has_next: false },
                '/api/environments/:team_id/session_recordings/properties': { results: [] },
            },
        })
        localStorage.clear()
        initKeaTests()
        ;(experimentsInSessionExposureRetrieve as jest.Mock).mockResolvedValue({
            available: true,
            unavailable_reason: null,
            uses_stamped_fallback: false,
        })
        ;(experimentsSessionBucketsCreate as jest.Mock).mockReset()
        jest.spyOn(api.propertyDefinitions, 'seenTogether').mockResolvedValue({})
        playlistLogic = sessionRecordingsPlaylistLogic(playlistProps)
        playlistLogic.mount()
        playerSettingsLogic.mount()
    })

    afterEach(() => {
        cleanup()
        playerSettingsLogic.actions.setHideViewedRecordings(false)
        playerSettingsLogic.unmount()
        playlistLogic.unmount()
        jest.restoreAllMocks()
        localStorage.clear()
    })

    function renderEmptyState(experiment: Experiment): void {
        render(
            <Provider>
                <BindLogic logic={sessionRecordingsPlaylistLogic} props={playlistProps}>
                    <ExperimentRecordingsListEmptyState experiment={experiment} />
                </BindLogic>
            </Provider>
        )
    }

    it.each(REASON_CASES)(
        'explains $reason and offers only the actions that fix it',
        async ({ experimentId, experiment, team, setup, copy, actions }) => {
            teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, ...team })
            const logic = experimentReplayTabLogic({
                experiment: { ...EXPERIMENT, id: experimentId, ...experiment } as Experiment,
            })
            logic.mount()
            setup?.(logic)
            await expectLogic(logic).toFinishAllListeners()
            renderEmptyState({ ...EXPERIMENT, id: experimentId, ...experiment } as Experiment)

            expect(screen.getByTestId('experiment-recordings-empty-state')).toHaveTextContent(copy)
            expect(ACTION_ATTRS.filter((attr) => screen.queryAllByTestId(attr).length > 0)).toEqual(actions)

            logic.unmount()
        }
    )

    it('names no reason while the metric filter is still being resolved', async () => {
        // An unanswered bucket has the same empty session set as one that matched nothing, so the
        // banner used to claim "matched nothing" and drop "Try again" for the length of the request.
        // A retry after a failure shows it worst: the list never reloads, so only the banner moves.
        teamLogic.actions.loadCurrentTeamSuccess(MOCK_DEFAULT_TEAM)
        let resolveBucket: (response: unknown) => void = () => {}
        ;(experimentsSessionBucketsCreate as jest.Mock).mockReturnValue(
            new Promise((resolve) => {
                resolveBucket = resolve
            })
        )
        const logic = experimentReplayTabLogic({
            experiment: { ...EXPERIMENT, id: 213 } as Experiment,
        })
        logic.mount()
        logic.actions.setMetricFilterMode('no_metric_activity')
        await waitFor(() => expect(logic.values.sessionBucketLoading).toBe(true))

        renderEmptyState({ ...EXPERIMENT, id: 213 } as Experiment)
        expect(screen.getByTestId('experiment-recordings-empty-state')).toBeEmptyDOMElement()

        resolveBucket({
            session_ids: [],
            truncated: false,
            considered_metrics: [],
            excluded_metrics: [],
            filter_test_accounts: true,
        })
        await waitFor(() =>
            expect(screen.getByTestId('experiment-recordings-empty-state')).toHaveTextContent(
                'No recordings matched the metric filter.'
            )
        )

        logic.unmount()
    })

    it('answers with the hidden recordings instead of a reason when the list only looks empty', async () => {
        teamLogic.actions.loadCurrentTeamSuccess(MOCK_DEFAULT_TEAM)
        playerSettingsLogic.actions.setHideViewedRecordings('current-user')
        const logic = experimentReplayTabLogic({ experiment: EXPERIMENT })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        // After the playlist's own first load, which resets the list as it starts.
        await waitFor(() => expect(playlistLogic.values.sessionRecordingsResponseLoading).toBe(false))
        // Rows the API returned, hidden in the browser because this viewer has watched them.
        playlistLogic.actions.loadSessionRecordingsSuccess({
            results: [
                { id: 's1', viewed: true },
                { id: 's2', viewed: true },
            ],
            has_next: false,
        } as any)

        renderEmptyState(EXPERIMENT)

        expect(playlistLogic.values.hiddenRecordingsCount).toBe(2)
        expect(screen.getByTestId('experiment-recordings-empty-show-hidden')).toHaveTextContent(
            'Show 2 hidden recordings'
        )
        expect(screen.queryByTestId('experiment-recordings-empty-state')).not.toHaveTextContent('A session can be')

        logic.unmount()
    })
})
