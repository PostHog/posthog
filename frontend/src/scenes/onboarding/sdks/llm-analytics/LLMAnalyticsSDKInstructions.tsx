import { AnthropicInstallation } from 'onboarding/anthropic'
import { GoogleInstallation } from 'onboarding/google'
import { LangChainInstallation } from 'onboarding/langchain'
import { LiteLLMInstallation } from 'onboarding/litellm'
import { OpenAIInstallation } from 'onboarding/openai'
import { OpenRouterInstallation } from 'onboarding/openrouter'
import { VercelAIInstallation } from 'onboarding/vercel-ai'

import { SDKInstructionsMap, SDKKey } from '~/types'

import { OnboardingContentWrapper } from './OnboardingContentWrapper'
import { LLMManualCaptureInstructions } from './manual'

function LLMOpenAIInstructions(): JSX.Element {
    return (
        <OnboardingContentWrapper>
            <OpenAIInstallation />
        </OnboardingContentWrapper>
    )
}

function LLMAnthropicInstructions(): JSX.Element {
    return (
        <OnboardingContentWrapper>
            <AnthropicInstallation />
        </OnboardingContentWrapper>
    )
}

function LLMGoogleInstructions(): JSX.Element {
    return (
        <OnboardingContentWrapper>
            <GoogleInstallation />
        </OnboardingContentWrapper>
    )
}

function LLMOpenRouterInstructions(): JSX.Element {
    return (
        <OnboardingContentWrapper>
            <OpenRouterInstallation />
        </OnboardingContentWrapper>
    )
}

function LLMLangChainInstructions(): JSX.Element {
    return (
        <OnboardingContentWrapper>
            <LangChainInstallation />
        </OnboardingContentWrapper>
    )
}

function LLMLiteLLMInstructions(): JSX.Element {
    return (
        <OnboardingContentWrapper>
            <LiteLLMInstallation />
        </OnboardingContentWrapper>
    )
}

function LLMVercelAIInstructions(): JSX.Element {
    return (
        <OnboardingContentWrapper>
            <VercelAIInstallation />
        </OnboardingContentWrapper>
    )
}

export const LLMAnalyticsSDKInstructions: SDKInstructionsMap = {
    [SDKKey.OPENAI]: LLMOpenAIInstructions,
    [SDKKey.ANTHROPIC]: LLMAnthropicInstructions,
    [SDKKey.GOOGLE_GEMINI]: LLMGoogleInstructions,
    [SDKKey.VERCEL_AI]: LLMVercelAIInstructions,
    [SDKKey.LANGCHAIN]: LLMLangChainInstructions,
    [SDKKey.LITELLM]: LLMLiteLLMInstructions,
    [SDKKey.OPENROUTER]: LLMOpenRouterInstructions,
    [SDKKey.MANUAL_CAPTURE]: LLMManualCaptureInstructions,
}
