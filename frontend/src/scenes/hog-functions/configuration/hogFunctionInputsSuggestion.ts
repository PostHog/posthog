import { CyclotronJobInputSchemaType, CyclotronJobInputType } from '~/types'

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
                retypedInputs.map((schema) => [schema.key, currentInputs[schema.key] ?? { value: null }])
            ),
            ...Object.fromEntries(
                Object.entries(inputs).map(([key, value]) => [key, { ...currentInputs[key], value }])
            ),
        },
    }
}
