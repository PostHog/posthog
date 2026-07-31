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

    // Metrics ingests over OTLP like Logs does, so picking both must not ask the user
    // to install OpenTelemetry twice.
    it('shares one OpenTelemetry install step between metrics and logs', () => {
        const metricsStep = onboardingProviderRegistry[ProductKey.METRICS]!.steps(context(ProductKey.METRICS))[0]
        const logsStep = onboardingProviderRegistry[ProductKey.LOGS]!.steps(context(ProductKey.LOGS))[0]

        expect(metricsStep.dedupKey).toBe(INSTALL_DEDUP_KEYS.OPENTELEMETRY)
        expect(logsStep.dedupKey).toBe(metricsStep.dedupKey)
    })
})
