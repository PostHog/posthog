import { PluginEvent } from '~/plugin-scaffold'

import { parseJSON } from '../../../../utils/json-parse'
import { OtelLibraryMiddleware } from './types'

const LOGFIRE_STRIP_KEYS = [
    'logfire.json_schema',
    'logfire.msg',
    'operation.cost',
    'model_request_parameters',
    'model_name',
    'gen_ai.usage.details.input_tokens',
    'gen_ai.usage.details.output_tokens',
]

function process(event: PluginEvent, next: () => void): void {
    if (!event.properties) {
        return next()
    }
    const props = event.properties

    next()

    // logfire.msg as fallback when $otel_span_name was empty
    if (props['$ai_span_name'] === undefined && props['logfire.msg'] !== undefined) {
        props['$ai_span_name'] = props['logfire.msg']
    }

    const isAgentRun = event.event === '$ai_trace' || props['pydantic_ai.all_messages'] !== undefined
    if (isAgentRun) {
        let messages: Record<string, unknown>[] | undefined
        const allMessages = props['pydantic_ai.all_messages']
        if (typeof allMessages === 'string') {
            try {
                const parsed = parseJSON(allMessages)
                if (Array.isArray(parsed)) {
                    messages = parsed.filter(
                        (item): item is Record<string, unknown> =>
                            typeof item === 'object' && item !== null && !Array.isArray(item)
                    )
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
            let finalResult = props['final_result']
            if (typeof finalResult === 'string') {
                try {
                    const parsed = parseJSON(finalResult)
                    if (typeof parsed === 'object' && parsed !== null) {
                        finalResult = parsed
                    }
                } catch {
                    // Keep original string
                }
            }
            props['$ai_output_state'] = finalResult
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

        if (props['$ai_model'] === undefined && props['model_name'] !== undefined) {
            props['$ai_model'] = props['model_name']
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
            let toolResponse = props['tool_response']
            if (typeof toolResponse === 'string') {
                try {
                    toolResponse = parseJSON(toolResponse)
                } catch {
                    // Keep original string
                }
            }
            props['$ai_output_state'] = toolResponse
        }

        if (props['gen_ai.tool.name'] !== undefined) {
            props['$ai_span_name'] = props['gen_ai.tool.name']
        }

        delete props['tool_arguments']
        delete props['tool_response']
        delete props['gen_ai.tool.name']
        delete props['gen_ai.tool.call.id']
    }

    props['$ai_lib'] = 'opentelemetry/pydantic-ai'

    for (const key of LOGFIRE_STRIP_KEYS) {
        delete props[key]
    }
}

const MARKER_KEYS = ['pydantic_ai.all_messages', 'logfire.msg', 'logfire.json_schema', 'model_request_parameters']

export const pydanticAi: OtelLibraryMiddleware = {
    name: 'pydantic-ai',
    matches: (event) => MARKER_KEYS.some((key) => event.properties?.[key] !== undefined),
    process,
}
