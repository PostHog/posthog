import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { SDKInstructionsMap, SDKKey } from '~/types'

import { EmbeddingEvent } from '../../../../../../docs/onboarding/llm-analytics/_snippets/embedding-event'
import { GenerationEvent } from '../../../../../../docs/onboarding/llm-analytics/_snippets/generation-event'
import { SpanEvent } from '../../../../../../docs/onboarding/llm-analytics/_snippets/span-event'
import { TraceEvent } from '../../../../../../docs/onboarding/llm-analytics/_snippets/trace-event'
import { AnthropicInstallation } from '../../../../../../docs/onboarding/llm-analytics/anthropic'
import { GoogleInstallation } from '../../../../../../docs/onboarding/llm-analytics/google'
import { LangChainInstallation } from '../../../../../../docs/onboarding/llm-analytics/langchain'
import { LiteLLMInstallation } from '../../../../../../docs/onboarding/llm-analytics/litellm'
import { ManualInstallation } from '../../../../../../docs/onboarding/llm-analytics/manual'
import { OpenAIInstallation } from '../../../../../../docs/onboarding/llm-analytics/openai'
import { OpenRouterInstallation } from '../../../../../../docs/onboarding/llm-analytics/openrouter'
import { VercelAIInstallation } from '../../../../../../docs/onboarding/llm-analytics/vercel-ai'

function LLMManualInstructions(): JSX.Element {
    const snippets = {
        GenerationEvent,
        TraceEvent,
        SpanEvent,
        EmbeddingEvent,
    }

    return (
        <OnboardingDocsContentWrapper snippets={snippets}>
            <ManualInstallation />
        </OnboardingDocsContentWrapper>
    )
}

function LLMOpenAIInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <OpenAIInstallation />
        </OnboardingDocsContentWrapper>
    )
}

function LLMAnthropicInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <AnthropicInstallation />
        </OnboardingDocsContentWrapper>
    )
}

function LLMGoogleInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <GoogleInstallation />
        </OnboardingDocsContentWrapper>
    )
}

function LLMOpenRouterInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <OpenRouterInstallation />
        </OnboardingDocsContentWrapper>
    )
}

function LLMLangChainInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <LangChainInstallation />
        </OnboardingDocsContentWrapper>
    )
}

function LLMLiteLLMInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <LiteLLMInstallation />
        </OnboardingDocsContentWrapper>
    )
}

function LLMVercelAIInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <VercelAIInstallation />
        </OnboardingDocsContentWrapper>
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
    [SDKKey.MANUAL_CAPTURE]: LLMManualInstructions,
}
