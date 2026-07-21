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
    ...overrides,
})

/** One of each interesting state: seen-and-jumpable, multi-variant warning, seen-but-out-of-window,
 * carried-over assignment. The recording window is 14:46:20–14:46:32 (see recording_meta mock). */
export const experimentSessionContextResponse: ExperimentSessionContextResponseApi = {
    session_id: 'experiment-context-session',
    results: [
        makeExperimentSessionContextItem(),
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
