import { PluginEvent } from '~/plugin-scaffold'

import { OtelLibraryMiddleware } from './types'

const STRIP_KEYS = [
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

/**
 * Reassembles OTel flattened indexed attributes back into structured arrays.
 *
 * Traceloop/OpenLLMetry emits messages as `gen_ai.prompt.0.role`, `gen_ai.prompt.0.content`,
 * `gen_ai.prompt.0.tool_calls.0.name`, etc. This function collects them by index and
 * rebuilds the structured form: `[{ role, content, tool_calls: [{ name, arguments }] }]`.
 */
export function reassembleIndexedAttributes(
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

        const index = Number(rest.slice(0, firstDot))
        if (!Number.isInteger(index) || index < 0) {
            continue
        }

        const afterIndex = rest.slice(firstDot + 1)

        if (!entries.has(index)) {
            entries.set(index, { index, fields: {}, nested: {} })
        }
        const entry = entries.get(index)!

        let matched = false
        for (const group of nestedGroups) {
            const nestedPrefix = group + '.'
            if (afterIndex.startsWith(nestedPrefix)) {
                const nestedRest = afterIndex.slice(nestedPrefix.length)
                const nestedDot = nestedRest.indexOf('.')
                if (nestedDot === -1) {
                    continue
                }
                const nestedIndex = Number(nestedRest.slice(0, nestedDot))
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

        if (!matched && topFieldSet.has(afterIndex)) {
            entry.fields[afterIndex] = props[key]
            consumedKeys.push(key)
        }
    }

    if (entries.size === 0) {
        return undefined
    }

    for (const key of consumedKeys) {
        delete props[key]
    }

    const sorted = Array.from(entries.values()).sort((a, b) => a.index - b.index)
    const result = sorted
        .map((entry) => {
            const obj: Record<string, unknown> = { ...entry.fields }
            for (const [group, nestedEntries] of Object.entries(entry.nested)) {
                obj[group] = nestedEntries.sort((a, b) => a.index - b.index).map((e) => e.fields)
            }
            return obj
        })
        .filter((obj) => Object.keys(obj).length > 0)

    return result.length > 0 ? result : undefined
}

function process(event: PluginEvent, next: () => void): void {
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

    for (const key of STRIP_KEYS) {
        delete props[key]
    }
    for (const key of Object.keys(props)) {
        if (key.startsWith('traceloop.association.properties.')) {
            delete props[key]
        }
    }
}

const MARKER_KEYS = ['llm.request.type', 'traceloop.span.kind', 'traceloop.entity.name']

export const traceloop: OtelLibraryMiddleware = {
    name: 'traceloop',
    matches: (event) => MARKER_KEYS.some((key) => event.properties?.[key] !== undefined),
    process,
}
