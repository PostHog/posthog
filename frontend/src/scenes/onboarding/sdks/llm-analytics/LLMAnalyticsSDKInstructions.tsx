import { SDKInstructionsMap, SDKKey } from '~/types'

import { LLMAnthropicInstructions } from './anthropic'
import { LLMGoogleInstructions } from './google'
import { LLMLangChainInstructions } from './langchain'
import { LLMLiteLLMInstructions } from './litellm'
import { LLMManualCaptureInstructions } from './manual'
import { LLMOpenAIInstructions } from './openai'
import { LLMOpenRouterInstructions } from './openrouter'
import { LLMVercelAIInstructions } from './vercel-ai'

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
