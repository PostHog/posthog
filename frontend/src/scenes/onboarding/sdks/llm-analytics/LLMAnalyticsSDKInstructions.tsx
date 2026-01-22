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

import { SDKInstructionsMap, SDKKey } from '~/types'

import { withOnboardingDocsWrapper } from '../shared/onboardingWrappers'

// Snippet configurations, defined once
const MANUAL_SNIPPETS = {
    GenerationEvent,
    TraceEvent,
    SpanEvent,
    EmbeddingEvent,
}

const PROVIDER_SNIPPETS = {
    NotableGenerationProperties,
}

// Manual capture, all event types
const LLMManualInstructionsWrapper = withOnboardingDocsWrapper(ManualInstallation, MANUAL_SNIPPETS)

// LLM Providers
const LLMOpenAIInstructionsWrapper = withOnboardingDocsWrapper(OpenAIInstallation, PROVIDER_SNIPPETS)
const LLMAnthropicInstructionsWrapper = withOnboardingDocsWrapper(AnthropicInstallation, PROVIDER_SNIPPETS)
const LLMGoogleInstructionsWrapper = withOnboardingDocsWrapper(GoogleInstallation, PROVIDER_SNIPPETS)
const LLMOpenRouterInstructionsWrapper = withOnboardingDocsWrapper(OpenRouterInstallation, PROVIDER_SNIPPETS)
const LLMLangChainInstructionsWrapper = withOnboardingDocsWrapper(LangChainInstallation, PROVIDER_SNIPPETS)
const LLMLiteLLMInstructionsWrapper = withOnboardingDocsWrapper(LiteLLMInstallation, PROVIDER_SNIPPETS)
const LLMVercelAIInstructionsWrapper = withOnboardingDocsWrapper(VercelAIInstallation, PROVIDER_SNIPPETS)

export const LLMAnalyticsSDKInstructions: SDKInstructionsMap = {
    [SDKKey.OPENAI]: LLMOpenAIInstructionsWrapper,
    [SDKKey.ANTHROPIC]: LLMAnthropicInstructionsWrapper,
    [SDKKey.GOOGLE_GEMINI]: LLMGoogleInstructionsWrapper,
    [SDKKey.VERCEL_AI]: LLMVercelAIInstructionsWrapper,
    [SDKKey.LANGCHAIN]: LLMLangChainInstructionsWrapper,
    [SDKKey.LITELLM]: LLMLiteLLMInstructionsWrapper,
    [SDKKey.OPENROUTER]: LLMOpenRouterInstructionsWrapper,
    [SDKKey.MANUAL_CAPTURE]: LLMManualInstructionsWrapper,
}
