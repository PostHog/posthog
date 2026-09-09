import { HogFlow, HogFlowAction } from '../schema/hogflow'

// One level only: `output.verdict`, not `output.a.b`. Nested paths still resolve at resume time
// through `result_path`, but the agent is only asked for top-level fields.
const OUTPUT_FIELD_PATH = /^output\.([A-Za-z_][A-Za-z0-9_]*)$/

const SCHEMA_TYPES: ReadonlySet<string> = new Set(['string', 'number', 'boolean'])

export type WorkflowTaskOutputSchema = {
    type: 'object'
    properties: Record<string, Record<string, unknown>>
    required: string[]
}

/**
 * The JSON Schema the AI task step asks the agent to fill, derived from the step's output
 * variables. Every mapping whose result path is `output.<name>` becomes one required property,
 * typed after the workflow variable it stores into, so the author never writes a schema by hand.
 * Returns null when no mapping reads from `output`.
 */
export const buildWorkflowTaskOutputSchema = (
    outputVariable: HogFlowAction['output_variable'],
    variables: HogFlow['variables']
): WorkflowTaskOutputSchema | null => {
    const mappings = Array.isArray(outputVariable) ? outputVariable : outputVariable ? [outputVariable] : []
    const variablesByKey = new Map((variables ?? []).map((variable) => [variable.key, variable]))
    const properties: Record<string, Record<string, unknown>> = {}

    for (const mapping of mappings) {
        const field = mapping.key ? OUTPUT_FIELD_PATH.exec(mapping.result_path ?? '')?.[1] : undefined
        if (!field) {
            continue
        }
        const variable = variablesByKey.get(mapping.key)
        const property: Record<string, unknown> = {}
        if (variable && SCHEMA_TYPES.has(variable.type)) {
            property.type = variable.type
        }
        const description = variable?.description || (variable?.label !== mapping.key ? variable?.label : undefined)
        if (description) {
            property.description = description
        }
        properties[field] = property
    }

    const required = Object.keys(properties)
    if (required.length === 0) {
        return null
    }
    return { type: 'object', properties, required }
}
