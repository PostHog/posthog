import { SetupTaskId } from 'lib/components/ProductSetup'
import {
    AIObservabilitySDKInstructions,
    AIObservabilitySDKTagOverrides,
} from 'scenes/onboarding/legacy/sdks/ai-observability/AIObservabilitySDKInstructions'
import { VERIFY_AI_EVENTS } from 'scenes/onboarding/legacy/sdks/hooks/useInstallationComplete'
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
                    teamPropertyToVerify={VERIFY_AI_EVENTS}
                    wizardOverrides={{
                        subcommand: 'ai-observability',
                        intro: 'The setup agent detects your LLM provider, installs the PostHog AI SDK, and instruments your AI calls automatically.',
                        description:
                            "Detects your LLM SDK and wires up tracing so generations, costs, and latency show up in AI observability. Commit the changes and open a PR when you're ready.",
                    }}
                />
            ),
        },
    ],
    completeRedirectUrl: () => urls.aiObservabilityDashboard(),
}
