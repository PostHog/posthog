import type {
    ExperimentSessionContextItemApi,
    ExperimentSessionContextResponseApi,
} from 'products/experiments/frontend/generated/api.schemas'

export const makeExperimentSessionContextItem = (
    overrides: Partial<ExperimentSessionContextItemApi> = {}
): ExperimentSessionContextItemApi => ({
    experiment_id: 101,
    experiment_name: 'Checkout CTA copy',
    flag_key: 'checkout-cta',
    variant: 'test',
    variants_seen: ['test'],
    multiple_variants: false,
    first_exposure_timestamp: '2023-05-01T14:46:24.000000Z',
    experiment_start_date: '2023-04-01T00:00:00Z',
    experiment_end_date: null,
    metrics_in_session: [],
    ...overrides,
})

/** One of each interesting state: seen-and-jumpable, multi-variant warning, seen-but-out-of-window,
 * carried-over assignment. The recording window is 14:46:20–14:46:32 (see recording_meta mock). */
export const experimentSessionContextResponse: ExperimentSessionContextResponseApi = {
    session_id: 'experiment-context-session',
    results: [
        makeExperimentSessionContextItem({
            metrics_in_session: [
                {
                    metric_uuid: 'metric-1',
                    metric_name: 'purchase completed',
                    event_count: 3,
                    // Inside the recording_meta mock's bounds — renders as a seekable jump link.
                    first_timestamp: '2023-05-01T14:46:26.000000Z',
                    // Three in-bounds occurrences — renders per-event seek chips.
                    timestamps: [
                        '2023-05-01T14:46:26.000000Z',
                        '2023-05-01T14:46:31.000000Z',
                        '2023-05-01T14:46:44.000000Z',
                    ],
                    // A mean metric's single source: no role qualifier, so it renders as the flat
                    // metric name plus its seek chips.
                    sources: [
                        {
                            source_role: 'source',
                            source_name: 'purchase completed',
                            source_index: 0,
                            source_total: 1,
                            event_count: 3,
                            first_timestamp: '2023-05-01T14:46:26.000000Z',
                            timestamps: [
                                '2023-05-01T14:46:26.000000Z',
                                '2023-05-01T14:46:31.000000Z',
                                '2023-05-01T14:46:44.000000Z',
                            ],
                        },
                    ],
                },
                {
                    metric_uuid: 'metric-2',
                    metric_name: 'checkout started',
                    event_count: 1,
                    // Outside the recording bounds (backend ±1h slack) — renders without a jump link.
                    first_timestamp: '2023-05-01T15:20:00.000000Z',
                    timestamps: ['2023-05-01T15:20:00.000000Z'],
                    sources: [
                        {
                            source_role: 'source',
                            source_name: 'checkout started',
                            source_index: 0,
                            source_total: 1,
                            event_count: 1,
                            first_timestamp: '2023-05-01T15:20:00.000000Z',
                            timestamps: ['2023-05-01T15:20:00.000000Z'],
                        },
                    ],
                },
                {
                    metric_uuid: 'metric-3',
                    metric_name: 'Signup funnel',
                    event_count: 2,
                    first_timestamp: '2023-05-01T14:46:25.000000Z',
                    timestamps: ['2023-05-01T14:46:25.000000Z', '2023-05-01T14:46:29.000000Z'],
                    // Only the middle step fired — the breakdown is what stops this reading as
                    // "completed the funnel".
                    sources: [
                        {
                            source_role: 'step',
                            source_name: 'activated',
                            source_index: 1,
                            source_total: 3,
                            event_count: 2,
                            first_timestamp: '2023-05-01T14:46:25.000000Z',
                            timestamps: ['2023-05-01T14:46:25.000000Z', '2023-05-01T14:46:29.000000Z'],
                        },
                    ],
                },
                {
                    metric_uuid: 'metric-4',
                    metric_name: '7-day retention',
                    event_count: 1,
                    first_timestamp: '2023-05-01T14:46:27.000000Z',
                    timestamps: ['2023-05-01T14:46:27.000000Z'],
                    // $pageview on both the start and return side: the return source would just
                    // duplicate the start's identical events, so only the start is contributed here.
                    sources: [
                        {
                            source_role: 'retention_start',
                            source_name: '$pageview',
                            source_index: 0,
                            source_total: 1,
                            event_count: 1,
                            first_timestamp: '2023-05-01T14:46:27.000000Z',
                            timestamps: ['2023-05-01T14:46:27.000000Z'],
                        },
                    ],
                },
            ],
        }),
        makeExperimentSessionContextItem({
            experiment_id: 102,
            experiment_name: 'Pricing page layout',
            flag_key: 'pricing-page-layout',
            variant: 'control',
            variants_seen: ['control', 'test'],
            multiple_variants: true,
        }),
        makeExperimentSessionContextItem({
            experiment_id: 104,
            experiment_name: 'Search bar placement',
            flag_key: 'search-bar-placement',
            variant: 'control',
            variants_seen: ['control'],
            // Exposure captured just before the recording's playable range — seen, but nothing to jump to.
            first_exposure_timestamp: '2023-05-01T14:45:00.000000Z',
        }),
        makeExperimentSessionContextItem({
            experiment_id: 103,
            experiment_name: 'Onboarding checklist',
            flag_key: 'onboarding-checklist',
            first_exposure_timestamp: null,
        }),
    ],
}
