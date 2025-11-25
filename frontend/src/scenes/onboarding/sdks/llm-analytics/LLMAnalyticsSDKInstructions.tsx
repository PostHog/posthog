import { SDKInstructionsMap, SDKKey } from '~/types'

import { AnthropicInstructionsFromMDX } from './AnthropicMDXInstructions'
import { GoogleInstructionsFromMDX } from './GoogleMDXInstructions'
import { LangChainInstructionsFromMDX } from './LangChainMDXInstructions'
import { LiteLLMInstructionsFromMDX } from './LiteLLMMDXInstructions'
import { ManualCaptureInstructionsFromMDX } from './ManualCaptureMDXInstructions'
import { OpenAIInstructionsFromMDX } from './OpenAIMDXInstructions'
import { OpenRouterInstructionsFromMDX } from './OpenRouterMDXInstructions'
import { VercelAIInstructionsFromMDX } from './VercelAIMDXInstructions'

export const LLMAnalyticsSDKInstructions: SDKInstructionsMap = {
    [SDKKey.OPENAI]: OpenAIInstructionsFromMDX,
    [SDKKey.ANTHROPIC]: AnthropicInstructionsFromMDX,
    [SDKKey.GOOGLE_GEMINI]: GoogleInstructionsFromMDX,
    [SDKKey.VERCEL_AI]: VercelAIInstructionsFromMDX,
    [SDKKey.LANGCHAIN]: LangChainInstructionsFromMDX,
    [SDKKey.LITELLM]: LiteLLMInstructionsFromMDX,
    [SDKKey.OPENROUTER]: OpenRouterInstructionsFromMDX,
    [SDKKey.MANUAL_CAPTURE]: ManualCaptureInstructionsFromMDX,
}
