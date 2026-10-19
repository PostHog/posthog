import { isObject } from 'lib/utils/guards'

import type { Message, MessageRole, MessageToolCall, PromptConfig, ReasoningLevel } from './llmPlaygroundPromptsLogic'

export interface PlaygroundModelConfig {
    model: string
    provider: string
    provider_key_id: string | null
}

// Config keys the playground owns. Serialization replaces exactly these keys and
// preserves everything else, so config written via the API survives a playground save.
const PLAYGROUND_CONFIG_KEYS = new Set([
    'model',
    'provider',
    'provider_key_id',
    'temperature',
    'max_tokens',
    'top_p',
    'thinking',
    'reasoning_effort',
    'tools',
    'messages',
])

const MESSAGE_ROLES: MessageRole[] = ['user', 'assistant', 'system', 'tool']
const REASONING_LEVELS: Exclude<ReasoningLevel, null>[] = ['minimal', 'low', 'medium', 'high']

export interface ParsedPlaygroundConfig {
    model: string | null
    provider: string | null
    providerKeyId: string | null
    temperature: number | null
    maxTokens: number | null
    topP: number | null
    thinking: boolean
    reasoningLevel: ReasoningLevel
    tools: Record<string, unknown>[] | null
    messages: Message[]
}

/**
 * Builds the config payload to store with a prompt version: the playground's model settings,
 * tools, and conversation messages, merged over any non-playground keys already in the
 * version's config. Variable placeholders in message content are stored raw, never substituted.
 * Returns null when there is nothing to store, so the version's config stays null.
 */
export function serializePlaygroundConfig(
    prompt: PromptConfig,
    modelConfig: PlaygroundModelConfig | null,
    existingConfig: unknown
): Record<string, unknown> | null {
    const config: Record<string, unknown> = {}
    if (isObject(existingConfig)) {
        for (const [key, value] of Object.entries(existingConfig)) {
            if (!PLAYGROUND_CONFIG_KEYS.has(key)) {
                config[key] = value
            }
        }
    }

    if (modelConfig) {
        config.model = modelConfig.model
        if (modelConfig.provider) {
            config.provider = modelConfig.provider
        }
        config.provider_key_id = modelConfig.provider_key_id
    } else if (isObject(existingConfig)) {
        // No panel model to write (nothing selected yet): carry the stored selection
        // forward instead of dropping it from the new version.
        for (const key of ['model', 'provider', 'provider_key_id']) {
            if (key in existingConfig) {
                config[key] = existingConfig[key]
            }
        }
    }
    if (prompt.temperature !== null) {
        config.temperature = prompt.temperature
    }
    if (prompt.maxTokens !== null) {
        config.max_tokens = prompt.maxTokens
    }
    if (prompt.topP !== null) {
        config.top_p = prompt.topP
    }
    config.thinking = prompt.thinking
    config.reasoning_effort = prompt.reasoningLevel
    if (prompt.tools && prompt.tools.length > 0) {
        config.tools = prompt.tools
    }
    if (prompt.messages.length > 0) {
        config.messages = prompt.messages.map((message) => ({
            role: message.role,
            content: message.content,
            ...(message.toolCalls?.length
                ? {
                      tool_calls: message.toolCalls.map((toolCall) => ({
                          id: toolCall.id,
                          name: toolCall.name,
                          arguments: toolCall.arguments,
                      })),
                  }
                : {}),
            ...(message.toolCallId ? { tool_call_id: message.toolCallId } : {}),
            ...(message.toolName ? { tool_name: message.toolName } : {}),
        }))
    }

    return Object.keys(config).length > 0 ? config : null
}

/**
 * Reads playground state back out of a stored prompt config. Returns null when the config
 * holds no playground-owned keys (old prompts, API-only configs), so the caller leaves the
 * panel untouched. Unrecognized keys and wrong-typed values are ignored, never an error.
 */
export function parsePlaygroundConfig(config: unknown): ParsedPlaygroundConfig | null {
    if (!isObject(config) || !Object.keys(config).some((key) => PLAYGROUND_CONFIG_KEYS.has(key))) {
        return null
    }

    const messages: Message[] = Array.isArray(config.messages)
        ? config.messages.flatMap((entry): Message[] => {
              if (
                  !isObject(entry) ||
                  !MESSAGE_ROLES.includes(entry.role as MessageRole) ||
                  typeof entry.content !== 'string'
              ) {
                  return []
              }
              const toolCalls: MessageToolCall[] = Array.isArray(entry.tool_calls)
                  ? entry.tool_calls.flatMap((call): MessageToolCall[] =>
                        isObject(call) &&
                        typeof call.id === 'string' &&
                        typeof call.name === 'string' &&
                        typeof call.arguments === 'string'
                            ? [{ id: call.id, name: call.name, arguments: call.arguments }]
                            : []
                    )
                  : []
              return [
                  {
                      role: entry.role as MessageRole,
                      content: entry.content,
                      ...(toolCalls.length > 0 ? { toolCalls } : {}),
                      ...(typeof entry.tool_call_id === 'string' && entry.tool_call_id
                          ? { toolCallId: entry.tool_call_id }
                          : {}),
                      ...(typeof entry.tool_name === 'string' && entry.tool_name ? { toolName: entry.tool_name } : {}),
                  },
              ]
          })
        : []

    const tools =
        Array.isArray(config.tools) && config.tools.length > 0 && config.tools.every(isObject)
            ? (config.tools as Record<string, unknown>[])
            : null

    return {
        model: typeof config.model === 'string' && config.model ? config.model : null,
        provider: typeof config.provider === 'string' && config.provider ? config.provider : null,
        providerKeyId:
            typeof config.provider_key_id === 'string' && config.provider_key_id ? config.provider_key_id : null,
        temperature:
            typeof config.temperature === 'number' && Number.isFinite(config.temperature) ? config.temperature : null,
        maxTokens:
            typeof config.max_tokens === 'number' && Number.isFinite(config.max_tokens) ? config.max_tokens : null,
        topP: typeof config.top_p === 'number' && Number.isFinite(config.top_p) ? config.top_p : null,
        thinking: config.thinking === true,
        reasoningLevel:
            'reasoning_effort' in config
                ? (REASONING_LEVELS.find((level) => level === config.reasoning_effort) ?? null)
                : 'medium',
        tools,
        messages,
    }
}
