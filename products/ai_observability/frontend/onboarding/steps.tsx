import { SetupTaskId } from 'lib/components/ProductSetup'
import {
    AIObservabilitySDKInstructions,
    AIObservabilitySDKTagOverrides,
} from 'scenes/onboarding/sdks/ai-observability/AIObservabilitySDKInstructions'
import { OnboardingInstallStep } from 'scenes/onboarding/sdks/OnboardingInstallStep'
import { type ProductOnboardingProvider } from 'scenes/onboarding/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

export const aiObservabilityOnboarding: ProductOnboardingProvider = {
    steps: (ctx) => [
        {
            id: `${OnboardingStepKey.INSTALL}:${ProductKey.LLM_ANALYTICS}`,
            productKey: ProductKey.LLM_ANALYTICS,
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
