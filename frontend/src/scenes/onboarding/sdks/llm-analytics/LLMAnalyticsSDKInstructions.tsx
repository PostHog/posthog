import { EmbeddingEvent } from '@posthog/shared-onboarding/llm-analytics/_snippets/embedding-event'
import { GenerationEvent } from '@posthog/shared-onboarding/llm-analytics/_snippets/generation-event'
import { NotableGenerationProperties } from '@posthog/shared-onboarding/llm-analytics/_snippets/notable-generation-properties'
import { SpanEvent } from '@posthog/shared-onboarding/llm-analytics/_snippets/span-event'
import { TraceEvent } from '@posthog/shared-onboarding/llm-analytics/_snippets/trace-event'
import { AnthropicInstallation } from '@posthog/shared-onboarding/llm-analytics/anthropic'
import { AutoGenInstallation } from '@posthog/shared-onboarding/llm-analytics/autogen'
import { AzureOpenAIInstallation } from '@posthog/shared-onboarding/llm-analytics/azure-openai'
import { CerebrasInstallation } from '@posthog/shared-onboarding/llm-analytics/cerebras'
import { CohereInstallation } from '@posthog/shared-onboarding/llm-analytics/cohere'
import { CrewAIInstallation } from '@posthog/shared-onboarding/llm-analytics/crewai'
import { DeepSeekInstallation } from '@posthog/shared-onboarding/llm-analytics/deepseek'
import { DSPyInstallation } from '@posthog/shared-onboarding/llm-analytics/dspy'
import { FireworksAIInstallation } from '@posthog/shared-onboarding/llm-analytics/fireworks-ai'
import { GoogleInstallation } from '@posthog/shared-onboarding/llm-analytics/google'
import { GroqInstallation } from '@posthog/shared-onboarding/llm-analytics/groq'
import { HeliconeInstallation } from '@posthog/shared-onboarding/llm-analytics/helicone'
import { HuggingFaceInstallation } from '@posthog/shared-onboarding/llm-analytics/hugging-face'
import { InstructorInstallation } from '@posthog/shared-onboarding/llm-analytics/instructor'
import { LangChainInstallation } from '@posthog/shared-onboarding/llm-analytics/langchain'
import { LangGraphInstallation } from '@posthog/shared-onboarding/llm-analytics/langgraph'
import { LiteLLMInstallation } from '@posthog/shared-onboarding/llm-analytics/litellm'
import { LlamaIndexInstallation } from '@posthog/shared-onboarding/llm-analytics/llamaindex'
import { ManualInstallation } from '@posthog/shared-onboarding/llm-analytics/manual'
import { MastraInstallation } from '@posthog/shared-onboarding/llm-analytics/mastra'
import { MirascopeInstallation } from '@posthog/shared-onboarding/llm-analytics/mirascope'
import { MistralInstallation } from '@posthog/shared-onboarding/llm-analytics/mistral'
import { OllamaInstallation } from '@posthog/shared-onboarding/llm-analytics/ollama'
import { OpenAIInstallation } from '@posthog/shared-onboarding/llm-analytics/openai'
import { OpenAIAgentsInstallation } from '@posthog/shared-onboarding/llm-analytics/openai-agents'
import { OpenRouterInstallation } from '@posthog/shared-onboarding/llm-analytics/openrouter'
import { PerplexityInstallation } from '@posthog/shared-onboarding/llm-analytics/perplexity'
import { PortkeyInstallation } from '@posthog/shared-onboarding/llm-analytics/portkey'
import { PydanticAIInstallation } from '@posthog/shared-onboarding/llm-analytics/pydantic-ai'
import { SemanticKernelInstallation } from '@posthog/shared-onboarding/llm-analytics/semantic-kernel'
import { SmolagentsInstallation } from '@posthog/shared-onboarding/llm-analytics/smolagents'
import { TogetherAIInstallation } from '@posthog/shared-onboarding/llm-analytics/together-ai'
import { VercelAIInstallation } from '@posthog/shared-onboarding/llm-analytics/vercel-ai'
import { VercelAIGatewayInstallation } from '@posthog/shared-onboarding/llm-analytics/vercel-ai-gateway'
import { XAIInstallation } from '@posthog/shared-onboarding/llm-analytics/xai'

import { SDKInstructionsMap, SDKKey, SDKTag, SDKTagOverrides } from '~/types'

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
const LLMVercelAIGatewayInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: VercelAIGatewayInstallation,
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
const LLMMastraInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: MastraInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMMirascopeInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: MirascopeInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMGroqInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: GroqInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMHeliconeInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: HeliconeInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMMistralInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: MistralInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMOllamaInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: OllamaInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMDeepSeekInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: DeepSeekInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMTogetherAIInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: TogetherAIInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMFireworksAIInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: FireworksAIInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMAzureOpenAIInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AzureOpenAIInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMCerebrasInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: CerebrasInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMPerplexityInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: PerplexityInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMPortkeyInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: PortkeyInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMCohereInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: CohereInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMHuggingFaceInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: HuggingFaceInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMXAIInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: XAIInstallation,
    snippets: PROVIDER_SNIPPETS,
})
const LLMOpenAIAgentsInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: OpenAIAgentsInstallation,
    snippets: PROVIDER_SNIPPETS,
})

export const LLMAnalyticsSDKTagOverrides: SDKTagOverrides = {
    [SDKKey.HELICONE]: [SDKTag.GATEWAY],
}

export const LLMAnalyticsSDKInstructions: SDKInstructionsMap = {
    [SDKKey.OPENAI]: LLMOpenAIInstructionsWrapper,
    [SDKKey.ANTHROPIC]: LLMAnthropicInstructionsWrapper,
    [SDKKey.GOOGLE_GEMINI]: LLMGoogleInstructionsWrapper,
    [SDKKey.VERCEL_AI]: LLMVercelAIInstructionsWrapper,
    [SDKKey.VERCEL_AI_GATEWAY]: LLMVercelAIGatewayInstructionsWrapper,
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
    [SDKKey.MASTRA]: LLMMastraInstructionsWrapper,
    [SDKKey.MIRASCOPE]: LLMMirascopeInstructionsWrapper,
    [SDKKey.GROQ]: LLMGroqInstructionsWrapper,
    [SDKKey.HELICONE]: LLMHeliconeInstructionsWrapper,
    [SDKKey.MISTRAL]: LLMMistralInstructionsWrapper,
    [SDKKey.OLLAMA]: LLMOllamaInstructionsWrapper,
    [SDKKey.DEEPSEEK]: LLMDeepSeekInstructionsWrapper,
    [SDKKey.TOGETHER_AI]: LLMTogetherAIInstructionsWrapper,
    [SDKKey.FIREWORKS_AI]: LLMFireworksAIInstructionsWrapper,
    [SDKKey.AZURE_OPENAI]: LLMAzureOpenAIInstructionsWrapper,
    [SDKKey.CEREBRAS]: LLMCerebrasInstructionsWrapper,
    [SDKKey.PERPLEXITY]: LLMPerplexityInstructionsWrapper,
    [SDKKey.PORTKEY]: LLMPortkeyInstructionsWrapper,
    [SDKKey.COHERE]: LLMCohereInstructionsWrapper,
    [SDKKey.HUGGING_FACE]: LLMHuggingFaceInstructionsWrapper,
    [SDKKey.XAI]: LLMXAIInstructionsWrapper,
    [SDKKey.OPENAI_AGENTS]: LLMOpenAIAgentsInstructionsWrapper,
    [SDKKey.MANUAL_CAPTURE]: LLMManualInstructionsWrapper,
}
