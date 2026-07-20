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
    seen_reason: 'exposure',
    ...overrides,
})

/** One of each interesting state: single variant, multi-variant warning, no in-session exposure event. */
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
            experiment_id: 103,
            experiment_name: 'Onboarding checklist',
            flag_key: 'onboarding-checklist',
            first_exposure_timestamp: null,
        }),
    ],
}
