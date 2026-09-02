import { SetupTaskId } from 'lib/components/ProductSetup'
import {
    AIObservabilitySDKInstructions,
    AIObservabilitySDKTagOverrides,
} from 'scenes/onboarding/legacy/sdks/ai-observability/AIObservabilitySDKInstructions'
import { VERIFY_AI_EVENTS } from 'scenes/onboarding/legacy/sdks/hooks/useInstallationComplete'
import { OnboardingInstallStep } from 'scenes/onboarding/legacy/sdks/OnboardingInstallStep'
import { type ProductOnboardingProvider } from 'scenes/onboarding/legacy/types'
import { AnthropicLogo } from 'scenes/onboarding/shared/logos/AnthropicLogo'
import geminiImage from 'scenes/onboarding/shared/logos/gemini.svg'
import { LangChainLogo } from 'scenes/onboarding/shared/logos/LangChainLogo'
import { OpenAILogo } from 'scenes/onboarding/shared/logos/OpenAILogo'
import { OpenRouterLogo } from 'scenes/onboarding/shared/logos/OpenRouterLogo'
import type { WizardBadgeItem } from 'scenes/onboarding/shared/wizard-sync/WizardModeShell'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

// Headline picks from the ~40 variants of the context-mill ai-observability skill group.
const AIO_WIZARD_SUPPORTS: WizardBadgeItem[] = [
    { name: 'OpenAI', icon: OpenAILogo },
    { name: 'Anthropic', icon: AnthropicLogo },
    { name: 'Google Gemini', icon: geminiImage },
    { name: 'AWS Bedrock', icon: 'https://res.cloudinary.com/dmukukwp6/image/upload/bedrock_5c06698148.png' },
    { name: 'Azure OpenAI', icon: 'https://res.cloudinary.com/dmukukwp6/image/upload/azure_openai_884ba0124a.svg' },
    { name: 'LangChain', icon: LangChainLogo },
    { name: 'LlamaIndex', icon: 'https://res.cloudinary.com/dmukukwp6/image/upload/llamaindex_f831132d7c.svg' },
    { name: 'Vercel AI SDK', icon: 'https://res.cloudinary.com/dmukukwp6/image/upload/vercel_373fa70879.svg' },
    {
        name: 'LiteLLM',
        icon: 'https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/litellmicon_a2805d75e5.png',
    },
    { name: 'Ollama', icon: 'https://res.cloudinary.com/dmukukwp6/image/upload/ollama_ff56896a1f.svg' },
    { name: 'Mistral', icon: 'https://res.cloudinary.com/dmukukwp6/image/upload/mistral_551c75e2dd.svg' },
    { name: 'OpenRouter', icon: OpenRouterLogo },
    { name: '+ 30 more' },
]

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
                        supports: AIO_WIZARD_SUPPORTS,
                    }}
                />
            ),
        },
    ],
    completeRedirectUrl: () => urls.aiObservabilityDashboard(),
}
