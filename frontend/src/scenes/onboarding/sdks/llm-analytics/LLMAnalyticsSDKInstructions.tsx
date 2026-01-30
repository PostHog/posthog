import { EmbeddingEvent } from '@posthog/shared-onboarding/llm-analytics/_snippets/embedding-event'
import { GenerationEvent } from '@posthog/shared-onboarding/llm-analytics/_snippets/generation-event'
import { NotableGenerationProperties } from '@posthog/shared-onboarding/llm-analytics/_snippets/notable-generation-properties'
import { SpanEvent } from '@posthog/shared-onboarding/llm-analytics/_snippets/span-event'
import { TraceEvent } from '@posthog/shared-onboarding/llm-analytics/_snippets/trace-event'
import { AnthropicInstallation } from '@posthog/shared-onboarding/llm-analytics/anthropic'
import { AutoGenInstallation } from '@posthog/shared-onboarding/llm-analytics/autogen'
import { CrewAIInstallation } from '@posthog/shared-onboarding/llm-analytics/crewai'
import { DSPyInstallation } from '@posthog/shared-onboarding/llm-analytics/dspy'
import { GoogleInstallation } from '@posthog/shared-onboarding/llm-analytics/google'
import { InstructorInstallation } from '@posthog/shared-onboarding/llm-analytics/instructor'
import { LangChainInstallation } from '@posthog/shared-onboarding/llm-analytics/langchain'
import { LangGraphInstallation } from '@posthog/shared-onboarding/llm-analytics/langgraph'
import { LiteLLMInstallation } from '@posthog/shared-onboarding/llm-analytics/litellm'
import { LlamaIndexInstallation } from '@posthog/shared-onboarding/llm-analytics/llamaindex'
import { ManualInstallation } from '@posthog/shared-onboarding/llm-analytics/manual'
import { OpenAIInstallation } from '@posthog/shared-onboarding/llm-analytics/openai'
import { OpenRouterInstallation } from '@posthog/shared-onboarding/llm-analytics/openrouter'
import { PydanticAIInstallation } from '@posthog/shared-onboarding/llm-analytics/pydantic-ai'
import { SemanticKernelInstallation } from '@posthog/shared-onboarding/llm-analytics/semantic-kernel'
import { SmolagentsInstallation } from '@posthog/shared-onboarding/llm-analytics/smolagents'
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
const LLMManualInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ManualInstallation,
    snippets: MANUAL_SNIPPETS,
})

// LLM Providers
const LLMOpenAIInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: OpenAIInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMAnthropicInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AnthropicInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMGoogleInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: GoogleInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMOpenRouterInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: OpenRouterInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMLangChainInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: LangChainInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMLiteLLMInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: LiteLLMInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMVercelAIInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: VercelAIInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMInstructorInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: InstructorInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMCrewAIInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: CrewAIInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMPydanticAIInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: PydanticAIInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMLlamaIndexInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: LlamaIndexInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMDSPyInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: DSPyInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMAutoGenInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AutoGenInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMSemanticKernelInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SemanticKernelInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMSmolagentsInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SmolagentsInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMLangGraphInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: LangGraphInstallation,
    snippets: PROVIDER_SNIPPETS,
})

export const LLMAnalyticsSDKInstructions: SDKInstructionsMap = {
    [SDKKey.OPENAI]: LLMOpenAIInstructionsWrapper,
    [SDKKey.ANTHROPIC]: LLMAnthropicInstructionsWrapper,
    [SDKKey.GOOGLE_GEMINI]: LLMGoogleInstructionsWrapper,
    [SDKKey.VERCEL_AI]: LLMVercelAIInstructionsWrapper,
    [SDKKey.LANGCHAIN]: LLMLangChainInstructionsWrapper,
    [SDKKey.LITELLM]: LLMLiteLLMInstructionsWrapper,
    [SDKKey.OPENROUTER]: LLMOpenRouterInstructionsWrapper,
    [SDKKey.INSTRUCTOR]: LLMInstructorInstructionsWrapper,
    [SDKKey.CREWAI]: LLMCrewAIInstructionsWrapper,
    [SDKKey.PYDANTIC_AI]: LLMPydanticAIInstructionsWrapper,
    [SDKKey.LLAMAINDEX]: LLMLlamaIndexInstructionsWrapper,
    [SDKKey.DSPY]: LLMDSPyInstructionsWrapper,
    [SDKKey.AUTOGEN]: LLMAutoGenInstructionsWrapper,
    [SDKKey.SEMANTIC_KERNEL]: LLMSemanticKernelInstructionsWrapper,
    [SDKKey.SMOLAGENTS]: LLMSmolagentsInstructionsWrapper,
    [SDKKey.LANGGRAPH]: LLMLangGraphInstructionsWrapper,
    [SDKKey.MANUAL_CAPTURE]: LLMManualInstructionsWrapper,
}
