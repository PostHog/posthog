import { parseJSON } from '~/common/utils/json-parse'
import { PluginEvent } from '~/plugin-scaffold'

import { liftStopReasonFromOutputChoices } from './stop-reason'
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

const TOOL_ARGUMENT_KEYS = ['gen_ai.tool.call.arguments', 'tool_arguments']
const TOOL_RESULT_KEYS = ['gen_ai.tool.call.result', 'tool_response']

function readToolState(props: NonNullable<PluginEvent['properties']>, keys: string[]): unknown {
    for (const key of keys) {
        const value = props[key]
        if (value === undefined) {
            continue
        }
        if (typeof value !== 'string') {
            return typeof value === 'object' && value !== null ? value : String(value)
        }
        try {
            const parsed = parseJSON(value)
            // Conversation normalization accepts containers and strings, but drops scalar primitives.
            return typeof parsed === 'object' && parsed !== null ? parsed : value
        } catch {
            return value
        }
    }
    return undefined
}

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

    // pydantic-ai reports the finish reason inside each `gen_ai.output.messages` entry, and the
    // generic mapping in next() renamed that attribute to $ai_output_choices.
    liftStopReasonFromOutputChoices(props)

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
        const toolArgs = readToolState(props, TOOL_ARGUMENT_KEYS)
        if (toolArgs !== undefined) {
            props['$ai_input_state'] = toolArgs
        }

        const toolResponse = readToolState(props, TOOL_RESULT_KEYS)
        if (toolResponse !== undefined) {
            props['$ai_output_state'] = toolResponse
        }

        if (props['gen_ai.tool.name'] !== undefined) {
            props['$ai_span_name'] = props['gen_ai.tool.name']
        }

        for (const key of [...TOOL_ARGUMENT_KEYS, ...TOOL_RESULT_KEYS]) {
            delete props[key]
        }
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
