import { HogFlow, HogFlowAction } from '../schema/hogflow'

// One level only: `output.verdict`, not `output.a.b`. Nested paths still resolve at resume time
// through `result_path`, but the agent is only asked for top-level fields.
const OUTPUT_FIELD_PATH = /^output\.([A-Za-z_][A-Za-z0-9_]*)$/

export type WorkflowTaskOutputFieldType = 'string' | 'number' | 'boolean'
const FIELD_TYPES: ReadonlySet<string> = new Set<WorkflowTaskOutputFieldType>(['string', 'number', 'boolean'])

export type WorkflowTaskOutputFields = Record<string, WorkflowTaskOutputFieldType>

/**
 * The fields the AI task step asks the agent for, derived from the step's output variables.
 * Every mapping whose result path is `output.<name>` becomes one field, typed after the
 * workflow variable it stores into. The tasks API builds the schema from this map.
 * Returns null when no mapping reads from `output`.
 */
export const buildWorkflowTaskOutputFields = (
    outputVariable: HogFlowAction['output_variable'],
    variables: HogFlow['variables']
): WorkflowTaskOutputFields | null => {
    const mappings = Array.isArray(outputVariable) ? outputVariable : outputVariable ? [outputVariable] : []
    const variablesByKey = new Map((variables ?? []).map((variable) => [variable.key, variable]))
    const fields: WorkflowTaskOutputFields = {}

    for (const mapping of mappings) {
        const field = mapping.key ? OUTPUT_FIELD_PATH.exec(mapping.result_path ?? '')?.[1] : undefined
        if (!field) {
            continue
        }
        const type = variablesByKey.get(mapping.key)?.type
        // A variable of another type, or none, still gets asked for: text is what any of them can hold.
        fields[field] = type && FIELD_TYPES.has(type) ? (type as WorkflowTaskOutputFieldType) : 'string'
    }

    return Object.keys(fields).length === 0 ? null : fields
}
