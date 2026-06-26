import { SetupTaskId } from 'lib/components/ProductSetup'
import {
    AIObservabilitySDKInstructions,
    AIObservabilitySDKTagOverrides,
} from 'scenes/onboarding/legacy/sdks/ai-observability/AIObservabilitySDKInstructions'
import { OnboardingInstallStep } from 'scenes/onboarding/legacy/sdks/OnboardingInstallStep'
import { type ProductOnboardingProvider } from 'scenes/onboarding/legacy/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

export const aiObservabilityOnboarding: ProductOnboardingProvider = {
    steps: (ctx) => [
        {
            id: `${OnboardingStepKey.INSTALL}:${ProductKey.AI_OBSERVABILITY}`,
            productKey: ProductKey.AI_OBSERVABILITY,
            stepKey: OnboardingStepKey.INSTALL,
            role: ctx.role,
            setupTaskId: SetupTaskId.IngestFirstLlmEvent,
            render: () => (
                <OnboardingInstallStep
                    sdkInstructionMap={AIObservabilitySDKInstructions}
                    sdkTagOverrides={AIObservabilitySDKTagOverrides}
                    listeningForName="LLM generation"
                />
            ),
        },
    ],
    completeRedirectUrl: () => urls.aiObservabilityDashboard(),
}
