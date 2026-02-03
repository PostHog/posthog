import { PluginEvent } from '@posthog/plugin-scaffold'

import { parseJSON } from '../../../utils/json-parse'
import { mapOtelAttributes } from './attribute-mapping'

type OtelProviderMiddleware = (event: PluginEvent, next: () => void) => void

const LOGFIRE_STRIP_KEYS = ['logfire.json_schema', 'logfire.msg', 'operation.cost']

function pydanticAiMiddleware(event: PluginEvent, next: () => void): void {
    const props = event.properties!

    next()

    // logfire.msg as fallback when $otel_span_name was empty
    if (props['$ai_span_name'] === undefined && props['logfire.msg'] !== undefined) {
        props['$ai_span_name'] = props['logfire.msg']
    }

    if (event.event === '$ai_trace') {
        let messages: Record<string, unknown>[] | undefined
        const allMessages = props['pydantic_ai.all_messages']
        if (typeof allMessages === 'string') {
            try {
                const parsed = parseJSON(allMessages)
                if (Array.isArray(parsed)) {
                    messages = parsed
                }
            } catch {
                // Keep as-is if parsing fails
            }
        }

        if (messages) {
            const userMessage = messages.find((m) => m.role === 'user')
            if (userMessage) {
                props['$ai_input_state'] = userMessage
            }
        }

        if (props['final_result'] !== undefined) {
            props['$ai_output_state'] = props['final_result']
        } else if (messages) {
            const lastAssistant = messages.findLast((m) => m.role !== 'user' && m.role !== 'system')
            if (lastAssistant) {
                props['$ai_output_state'] = lastAssistant
            }
        }

        const agentName = props['gen_ai.agent.name'] ?? props['agent_name']
        if (agentName !== undefined) {
            props['$ai_span_name'] = agentName
        }

        delete props['pydantic_ai.all_messages']
        delete props['final_result']
        delete props['agent_name']
        delete props['gen_ai.agent.name']
    }

    if (event.event === '$ai_span') {
        if (props['tool_arguments'] !== undefined) {
            let toolArgs = props['tool_arguments']
            if (typeof toolArgs === 'string') {
                try {
                    toolArgs = parseJSON(toolArgs)
                } catch {
                    // Keep original string
                }
            }
            props['$ai_input_state'] = toolArgs
        }

        if (props['tool_response'] !== undefined) {
            props['$ai_output_state'] = props['tool_response']
        }

        if (props['gen_ai.tool.name'] !== undefined) {
            props['$ai_span_name'] = props['gen_ai.tool.name']
        }

        delete props['tool_arguments']
        delete props['tool_response']
        delete props['gen_ai.tool.name']
        delete props['gen_ai.tool.call.id']
    }

    for (const key of LOGFIRE_STRIP_KEYS) {
        delete props[key]
    }
}

const PROVIDER_MIDDLEWARE: Record<string, OtelProviderMiddleware> = {
    'pydantic-ai': pydanticAiMiddleware,
}

function detectProvider(event: PluginEvent): string | undefined {
    const system = event.properties?.['gen_ai.system']
    if (typeof system === 'string') {
        return system
    }
    const providerName = event.properties?.['gen_ai.provider.name']
    if (typeof providerName === 'string') {
        return providerName
    }
    if (
        event.properties?.['pydantic_ai.all_messages'] !== undefined ||
        event.properties?.['logfire.msg'] !== undefined
    ) {
        return 'pydantic-ai'
    }
    return undefined
}

export function convertOtelEvent(event: PluginEvent): void {
    const provider = detectProvider(event)
    const middleware = provider ? PROVIDER_MIDDLEWARE[provider] : undefined

    if (middleware) {
        middleware(event, () => mapOtelAttributes(event))
    } else {
        mapOtelAttributes(event)
    }
}
