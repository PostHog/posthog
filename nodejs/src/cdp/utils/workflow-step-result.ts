import { get } from 'lodash'

import { HogFlowAction } from '../schema/hogflow'

const VARIABLES_BYTE_CAP = 5120
const RESULT_STRING_CAP = 1500

const jsonBytes = (value: unknown): number => Buffer.byteLength(JSON.stringify(value), 'utf8')

const truncateValues = (value: unknown, cap: number): unknown => {
    if (typeof value === 'string') {
        return cap ? Array.from(value).slice(0, cap).join('') : undefined
    }
    if (Array.isArray(value)) {
        return value.slice(0, cap).flatMap((item) => {
            if (typeof item === 'string') {
                return Array.from(item).length <= cap ? [item] : []
            }
            const truncated = truncateValues(item, cap)
            return truncated === undefined ? [] : [truncated]
        })
    }
    if (value && typeof value === 'object') {
        return Object.fromEntries(
            Object.entries(value)
                .map(([key, item]) => [key, truncateValues(item, cap)])
                .filter(([, item]) => item !== undefined)
        )
    }
    return value
}

export const capWorkflowStepResult = (
    dispatch: Record<string, unknown>,
    payload: Record<string, unknown>,
    variables: Record<string, unknown>,
    outputVariable: HogFlowAction['output_variable']
): Record<string, unknown> => {
    const { run_id: runId, ...content } = payload
    const fixed = { ...dispatch, ...(runId === undefined ? {} : { run_id: runId }) }
    const outputVariables = Array.isArray(outputVariable) ? outputVariable : outputVariable ? [outputVariable] : []

    const fits = (candidate: Record<string, unknown>): boolean => {
        if (jsonBytes(candidate) > VARIABLES_BYTE_CAP) {
            return false
        }
        const stored = { ...variables }
        for (const output of outputVariables) {
            if (!output.key) {
                continue
            }
            const resolved = output.result_path ? get(candidate, output.result_path) : candidate
            if (output.spread && resolved && typeof resolved === 'object' && !Array.isArray(resolved)) {
                for (const [key, value] of Object.entries(resolved)) {
                    stored[`${output.key}_${key}`] = value
                }
            } else {
                stored[output.key] = resolved
            }
        }
        return jsonBytes(stored) <= VARIABLES_BYTE_CAP
    }

    let lower = 0
    let upper = RESULT_STRING_CAP
    let result: Record<string, unknown> | undefined
    while (lower <= upper) {
        const midpoint = Math.floor((lower + upper) / 2)
        const candidate = { ...(truncateValues(content, midpoint) as Record<string, unknown>), ...fixed }
        if (fits(candidate)) {
            result = candidate
            lower = midpoint + 1
        } else {
            upper = midpoint - 1
        }
    }
    if (result) {
        return result
    }
    if (!fits(fixed)) {
        throw new Error('Workflow variables exceed the 5KB limit. Store fewer result fields.')
    }
    return fixed
}
