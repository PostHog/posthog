import { EmbeddingEvent } from '@posthog/shared-onboarding/llm-analytics/_snippets/embedding-event'
import { GenerationEvent } from '@posthog/shared-onboarding/llm-analytics/_snippets/generation-event'
import { NotableGenerationProperties } from '@posthog/shared-onboarding/llm-analytics/_snippets/notable-generation-properties'
import { SpanEvent } from '@posthog/shared-onboarding/llm-analytics/_snippets/span-event'
import { TraceEvent } from '@posthog/shared-onboarding/llm-analytics/_snippets/trace-event'
import { AnthropicInstallation } from '@posthog/shared-onboarding/llm-analytics/anthropic'
import { GoogleInstallation } from '@posthog/shared-onboarding/llm-analytics/google'
import { LangChainInstallation } from '@posthog/shared-onboarding/llm-analytics/langchain'
import { LiteLLMInstallation } from '@posthog/shared-onboarding/llm-analytics/litellm'
import { ManualInstallation } from '@posthog/shared-onboarding/llm-analytics/manual'
import { OpenAIInstallation } from '@posthog/shared-onboarding/llm-analytics/openai'
import { OpenRouterInstallation } from '@posthog/shared-onboarding/llm-analytics/openrouter'
import { VercelAIInstallation } from '@posthog/shared-onboarding/llm-analytics/vercel-ai'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { SDKInstructionsMap, SDKKey } from '~/types'

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

function LLMAnthropicInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper snippets={{ NotableGenerationProperties }}>
            <AnthropicInstallation />
        </OnboardingDocsContentWrapper>
    )
}

function LLMOpenAIInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper snippets={{ NotableGenerationProperties }}>
            <OpenAIInstallation />
        </OnboardingDocsContentWrapper>
    )
}

function LLMGoogleInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper snippets={{ NotableGenerationProperties }}>
            <GoogleInstallation />
        </OnboardingDocsContentWrapper>
    )
}

function LLMOpenRouterInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper snippets={{ NotableGenerationProperties }}>
            <OpenRouterInstallation />
        </OnboardingDocsContentWrapper>
    )
}

function LLMLangChainInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper snippets={{ NotableGenerationProperties }}>
            <LangChainInstallation />
        </OnboardingDocsContentWrapper>
    )
}

function LLMLiteLLMInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper snippets={{ NotableGenerationProperties }}>
            <LiteLLMInstallation />
        </OnboardingDocsContentWrapper>
    )
}

function LLMVercelAIInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper snippets={{ NotableGenerationProperties }}>
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
