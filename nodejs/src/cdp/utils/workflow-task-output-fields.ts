import { HogFlow, HogFlowAction } from '../schema/hogflow'

// One level only: `output.verdict`, not `output.a.b`. Nested paths still resolve at resume time
// through `result_path`, but the agent is only asked for top-level fields.
const OUTPUT_FIELD_PATH = /^output\.([A-Za-z_][A-Za-z0-9_]*)$/

export type WorkflowTaskOutputFieldType = 'string' | 'number' | 'boolean' | 'json'
const FIELD_TYPES: ReadonlySet<string> = new Set<WorkflowTaskOutputFieldType>(['string', 'number', 'boolean', 'json'])

export type WorkflowTaskOutputRequest = {
    output_fields: Record<string, WorkflowTaskOutputFieldType>
    output_field_descriptions?: Record<string, string>
}

/**
 * The fields the AI task step asks the agent for, derived from the step's output variables.
 * Every mapping whose result path is `output.<name>` becomes one field, typed after the
 * workflow variable it stores into and described by that variable's description. The tasks
 * API builds the schema from this. Returns null when no mapping reads from `output`.
 */
export const buildWorkflowTaskOutputFields = (
    outputVariable: HogFlowAction['output_variable'],
    variables: HogFlow['variables']
): WorkflowTaskOutputRequest | null => {
    const mappings = Array.isArray(outputVariable) ? outputVariable : outputVariable ? [outputVariable] : []
    const variablesByKey = new Map((variables ?? []).map((variable) => [variable.key, variable]))
    const fields: Record<string, WorkflowTaskOutputFieldType> = {}
    const descriptions: Record<string, string> = {}

    for (const mapping of mappings) {
        const field = mapping.key ? OUTPUT_FIELD_PATH.exec(mapping.result_path ?? '')?.[1] : undefined
        if (!field) {
            continue
        }
        const variable = variablesByKey.get(mapping.key)
        // A variable of another type, or none, still gets asked for: text is what any of them can hold.
        fields[field] =
            variable?.type && FIELD_TYPES.has(variable.type) ? (variable.type as WorkflowTaskOutputFieldType) : 'string'
        // Two mappings can read the same field: the last one sets the type, so it sets the description too.
        if (variable?.description) {
            descriptions[field] = variable.description
        } else {
            delete descriptions[field]
        }
    }

    if (Object.keys(fields).length === 0) {
        return null
    }
    return Object.keys(descriptions).length > 0
        ? { output_fields: fields, output_field_descriptions: descriptions }
        : { output_fields: fields }
}
