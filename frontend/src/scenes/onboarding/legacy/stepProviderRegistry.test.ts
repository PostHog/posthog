import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import { availableOnboardingProducts } from '../shared/utils'
import { onboardingProviderRegistry } from './stepProviderRegistry'
import { INSTALL_DEDUP_KEYS, type OnboardingFlowContext } from './types'

function context(primary: ProductKey): OnboardingFlowContext {
    return {
        primary,
        secondaries: [],
        role: 'primary',
        currentTeam: null,
        billing: null,
        isCloudOrDev: true,
        subscribedDuringOnboarding: false,
        canInviteTeammates: true,
        featureFlags: {},
        showAIReportsStep: false,
    }
}

describe('onboardingProviderRegistry', () => {
    // Onboarding a product means registering it twice: here for its steps, and in
    // availableOnboardingProducts for the picker. Either half alone ships a product
    // that can't be picked, or one that picks into a flow with no steps.
    it('covers exactly the products the picker offers', () => {
        expect(Object.keys(onboardingProviderRegistry).sort()).toEqual(Object.keys(availableOnboardingProducts).sort())
    })

    it('sends metrics through an install step and lands on the metrics scene', () => {
        const provider = onboardingProviderRegistry[ProductKey.METRICS]

        const steps = provider!.steps(context(ProductKey.METRICS))

        expect(steps).toHaveLength(1)
        expect(steps[0].productKey).toBe(ProductKey.METRICS)
        expect(steps[0].stepKey).toBe(OnboardingStepKey.INSTALL)
        expect(provider!.completeRedirectUrl?.()).toBe('/metrics')
    })

    // Metrics and Logs both arrive over OTel, but their install experiences differ:
    // Metrics is OTLP/scrape-agent only, while Logs offers Node.js, Python, Go, Java,
    // and mobile SDK flows. Sharing a dedupKey would collapse the two and drop the
    // loser's instruction map, so Metrics must NOT carry the OpenTelemetry dedupKey.
    it('does not share the OpenTelemetry dedup key with logs', () => {
        const metricsStep = onboardingProviderRegistry[ProductKey.METRICS]!.steps(context(ProductKey.METRICS))[0]
        const logsStep = onboardingProviderRegistry[ProductKey.LOGS]!.steps(context(ProductKey.LOGS))[0]

        expect(logsStep.dedupKey).toBe(INSTALL_DEDUP_KEYS.OPENTELEMETRY)
        expect(metricsStep.dedupKey).toBeUndefined()
    })
})
