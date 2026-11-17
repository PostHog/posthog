import { CyclotronJobInputSchemaType, CyclotronJobInputType, HogFunctionTypeType } from '~/types'

export type HogFunctionDeliveryType = 'batch' | 'realtime'

// Batch exports vs realtime destinations share `type: 'destination'`; the only signal is the id prefix.
export function getHogFunctionDeliveryType(item: { id: string }): HogFunctionDeliveryType {
    return item.id.startsWith('batch-export-') ? 'batch' : 'realtime'
}

export function humanizeHogFunctionType(type: HogFunctionTypeType, plural: boolean = false): string {
    if (type === 'source_webhook') {
        return 'source' + (plural ? 's' : '')
    }
    if (type === 'internal_destination') {
        return 'notification' + (plural ? 's' : '')
    }
    if (type === 'site_app') {
        return 'Web script' + (plural ? 's' : '')
    }
    if (type === 'transformation_log') {
        return 'log transformation' + (plural ? 's' : '')
    }
    return type.replaceAll('_', ' ') + (plural ? 's' : '')
}

/** Default char cap for a config blob attached to the PostHog AI agent as context. */
export const HOG_FUNCTION_CONTEXT_MAX_CHARS = 10_000

/**
 * Caps a stringified config blob before it's registered as PostHog AI attached context, so a pathological
 * hog source or inputs payload can't bloat the agent's context window. These are keyed entity-style items
 * (not `type: 'text'`), so they're sent once per run rather than every turn; the cap is a safety ceiling.
 */
export function truncateHogFunctionContext(value: string, max: number = HOG_FUNCTION_CONTEXT_MAX_CHARS): string {
    return value.length > max ? value.slice(0, max) + '… (truncated)' : value
}

export type HogFunctionInputsToolOutput = {
    inputs_schema: CyclotronJobInputSchemaType[]
    inputs: Record<string, unknown>
}

export type HogFunctionInputsSuggestion = {
    inputsSchema: CyclotronJobInputSchemaType[]
    inputValues: Record<string, CyclotronJobInputType>
}

/**
 * Reads the answer of the PostHog AI inputs tool. A backend deployed before the tool could change values
 * returns the bare schema list, so both shapes stay valid while a deploy rolls out.
 *
 * An input whose type the suggestion changes keeps its current value as a pending value. The preview renders
 * it with the new type's editor, and that editor can report a converted value back, which must not reach the
 * form before the suggestion is accepted.
 */
export function hogFunctionInputsSuggestion(
    toolOutput: HogFunctionInputsToolOutput | CyclotronJobInputSchemaType[],
    currentInputs: Record<string, CyclotronJobInputType>,
    currentInputsSchema: CyclotronJobInputSchemaType[]
): HogFunctionInputsSuggestion {
    const { inputs_schema, inputs } = Array.isArray(toolOutput) ? { inputs_schema: toolOutput, inputs: {} } : toolOutput
    const currentTypes = new Map(currentInputsSchema.map((schema) => [schema.key, schema.type]))
    const retypedInputs = inputs_schema.filter(
        (schema) => currentTypes.has(schema.key) && currentTypes.get(schema.key) !== schema.type
    )
    return {
        inputsSchema: inputs_schema,
        inputValues: {
            ...Object.fromEntries(
                retypedInputs
                    .filter((schema) => currentInputs[schema.key])
                    .map((schema) => [schema.key, currentInputs[schema.key]])
            ),
            ...Object.fromEntries(
                Object.entries(inputs).map(([key, value]) => [key, { ...currentInputs[key], value }])
            ),
        },
    }
}

/**
 * Replaces secret input values with a placeholder before the live form config leaves the scene (agent
 * context, approval-card diffs). A saved secret comes back masked from the API, but a value the user
 * just typed sits in form state in cleartext and must never reach the LLM. An entry counts as secret
 * when the schema marks its key secret or the entry itself carries `secret: true`.
 */
export function redactSecretHogFunctionInputs(
    inputs: Record<string, CyclotronJobInputType>,
    inputsSchema: CyclotronJobInputSchemaType[]
): Record<string, CyclotronJobInputType> {
    const secretKeys = new Set(inputsSchema.filter((schema) => schema.secret).map((schema) => schema.key))
    return Object.fromEntries(
        Object.entries(inputs).map(([key, entry]) => {
            const isSecret = secretKeys.has(key) || entry?.secret === true
            return [key, isSecret && entry ? { ...entry, value: '[secret]' } : entry]
        })
    )
}
