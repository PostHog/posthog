import { PluginEvent } from '~/plugin-scaffold'

import { parseJSON } from '../../../utils/json-parse'
import { mapOtelAttributes } from './attribute-mapping'

type OtelLibraryMiddleware = (event: PluginEvent, next: () => void) => void

const LOGFIRE_STRIP_KEYS = [
    'logfire.json_schema',
    'logfire.msg',
    'operation.cost',
    'model_request_parameters',
    'model_name',
    'gen_ai.usage.details.input_tokens',
    'gen_ai.usage.details.output_tokens',
]

function pydanticAiMiddleware(event: PluginEvent, next: () => void): void {
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

const TRACELOOP_STRIP_KEYS = [
    'traceloop.span.kind',
    'traceloop.entity.name',
    'traceloop.entity.path',
    'traceloop.workflow.name',
    'traceloop.entity.input',
    'traceloop.entity.output',
    'llm.is_streaming',
    'llm.usage.total_tokens',
    'llm.response.finish_reason',
    'llm.response.stop_reason',
]

interface IndexedEntry {
    index: number
    fields: Record<string, unknown>
    nested: Record<string, IndexedEntry[]>
}

function reassembleIndexedAttributes(
    props: Record<string, unknown>,
    prefix: string,
    topFields: string[],
    nestedGroups: string[]
): Record<string, unknown>[] | undefined {
    const entries = new Map<number, IndexedEntry>()
    const consumedKeys: string[] = []
    const topFieldSet = new Set(topFields)

    for (const key of Object.keys(props)) {
        if (!key.startsWith(prefix)) {
            continue
        }

        const rest = key.slice(prefix.length)
        const firstDot = rest.indexOf('.')
        if (firstDot === -1) {
            continue
        }

        const indexStr = rest.slice(0, firstDot)
        const index = Number(indexStr)
        if (!Number.isInteger(index) || index < 0) {
            continue
        }

        const afterIndex = rest.slice(firstDot + 1)

        if (!entries.has(index)) {
            entries.set(index, { index, fields: {}, nested: {} })
        }
        const entry = entries.get(index)!

        // Check if this is a nested group: e.g. tool_calls.0.function.name
        let matched = false
        for (const group of nestedGroups) {
            const nestedPrefix = group + '.'
            if (afterIndex.startsWith(nestedPrefix)) {
                const nestedRest = afterIndex.slice(nestedPrefix.length)
                const nestedDot = nestedRest.indexOf('.')
                if (nestedDot === -1) {
                    continue
                }
                const nestedIndexStr = nestedRest.slice(0, nestedDot)
                const nestedIndex = Number(nestedIndexStr)
                if (!Number.isInteger(nestedIndex) || nestedIndex < 0) {
                    continue
                }
                const nestedField = nestedRest.slice(nestedDot + 1)
                if (!entry.nested[group]) {
                    entry.nested[group] = []
                }
                let nestedEntry = entry.nested[group].find((e) => e.index === nestedIndex)
                if (!nestedEntry) {
                    nestedEntry = { index: nestedIndex, fields: {}, nested: {} }
                    entry.nested[group].push(nestedEntry)
                }
                nestedEntry.fields[nestedField] = props[key]
                consumedKeys.push(key)
                matched = true
                break
            }
        }

        if (!matched) {
            if (topFieldSet.has(afterIndex)) {
                entry.fields[afterIndex] = props[key]
                consumedKeys.push(key)
            }
        }
    }

    if (entries.size === 0) {
        return undefined
    }

    for (const key of consumedKeys) {
        delete props[key]
    }

    const sorted = Array.from(entries.values()).sort((a, b) => a.index - b.index)
    return sorted.map((entry) => {
        const obj: Record<string, unknown> = { ...entry.fields }
        for (const [group, nestedEntries] of Object.entries(entry.nested)) {
            obj[group] = nestedEntries.sort((a, b) => a.index - b.index).map((e) => e.fields)
        }
        return obj
    })
}

function traceloopMiddleware(event: PluginEvent, next: () => void): void {
    if (!event.properties) {
        return next()
    }
    const props = event.properties

    next()

    if (props['$ai_input'] === undefined) {
        const messages = reassembleIndexedAttributes(
            props,
            'gen_ai.prompt.',
            ['role', 'content', 'tool_call_id'],
            ['tool_calls']
        )
        if (messages) {
            props['$ai_input'] = messages
        }
    }

    if (props['$ai_output_choices'] === undefined) {
        const completions = reassembleIndexedAttributes(props, 'gen_ai.completion.', ['role', 'content'], [])
        if (completions) {
            props['$ai_output_choices'] = completions
        }
    }

    if (props['$ai_tools'] === undefined) {
        const tools = reassembleIndexedAttributes(
            props,
            'llm.request.functions.',
            ['name', 'description', 'parameters'],
            []
        )
        if (tools) {
            props['$ai_tools'] = tools
        }
    }

    props['$ai_lib'] = 'opentelemetry/traceloop'

    for (const key of TRACELOOP_STRIP_KEYS) {
        delete props[key]
    }
    // Strip all traceloop.association.properties.* keys
    for (const key of Object.keys(props)) {
        if (key.startsWith('traceloop.association.properties.')) {
            delete props[key]
        }
    }
}

const LIBRARY_MIDDLEWARE: Record<string, OtelLibraryMiddleware> = {
    'pydantic-ai': pydanticAiMiddleware,
    traceloop: traceloopMiddleware,
}

const PYDANTIC_MARKER_KEYS = [
    'pydantic_ai.all_messages',
    'logfire.msg',
    'logfire.json_schema',
    'model_request_parameters',
]

const TRACELOOP_MARKER_KEYS = ['llm.request.type', 'traceloop.span.kind', 'traceloop.entity.name']

function detectLibrary(event: PluginEvent): string | undefined {
    if (PYDANTIC_MARKER_KEYS.some((key) => event.properties?.[key] !== undefined)) {
        return 'pydantic-ai'
    }
    if (TRACELOOP_MARKER_KEYS.some((key) => event.properties?.[key] !== undefined)) {
        return 'traceloop'
    }
    return undefined
}

export function convertOtelEvent(event: PluginEvent): void {
    const library = detectLibrary(event)
    const middleware = library ? LIBRARY_MIDDLEWARE[library] : undefined

    if (middleware) {
        middleware(event, () => mapOtelAttributes(event))
    } else {
        mapOtelAttributes(event)
    }
}
