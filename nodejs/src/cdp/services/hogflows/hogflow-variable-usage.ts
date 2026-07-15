import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { HogFlowAction } from '~/cdp/schema/hogflow'
import { CyclotronJobInvocationHogFlow, CyclotronJobInvocationResult } from '~/cdp/types'
import { logger } from '~/common/utils/logger'

import { actionIdForLogging } from './hogflow-utils'

const counterMissingVariableReference = new Counter({
    name: 'cdp_hogflow_missing_variable_reference',
    help: 'A workflow step referenced a variable that is not set for the run, so it renders empty',
    labelNames: ['hog_flow_id'],
})

// Both templating modes reference workflow variables textually: `{variables.foo}` (hog) and
// `{{ variables.foo }}` (liquid), plus the bracket form `variables['my-var']`. A regex scan over
// the raw template strings covers both without parsing either language. Compiled hog bytecode
// never matches (it stores 'variables' and the key as separate string constants), so scanning a
// whole config is safe.
const DOT_REFERENCE_REGEX = /\bvariables\.([A-Za-z_$][A-Za-z0-9_$]*)/g
// Whitespace allowed around the brackets and quotes - liquid accepts `variables[ 'x' ]`
const BRACKET_REFERENCE_REGEX = /\bvariables\s*\[\s*['"]([^'"\]]+)['"]\s*\]/g

const collectReferences = (value: unknown, into: Set<string>): void => {
    if (typeof value === 'string') {
        for (const regex of [DOT_REFERENCE_REGEX, BRACKET_REFERENCE_REGEX]) {
            for (const match of value.matchAll(regex)) {
                into.add(match[1])
            }
        }
        return
    }
    if (Array.isArray(value)) {
        value.forEach((item) => collectReferences(item, into))
        return
    }
    if (value && typeof value === 'object') {
        Object.values(value).forEach((item) => collectReferences(item, into))
    }
}

/**
 * Names of workflow variables referenced anywhere in the action's inputs/mappings that are not
 * present on the run's variable map. Declared variables are always seeded onto the run (with a
 * null default), so an absent key means the run genuinely never had the variable: it was renamed
 * or removed after the run started, or an output_variable whose producing step never ran for
 * this run. Those references render empty - this makes that observable.
 */
export function findMissingVariableReferences(
    config: { inputs?: unknown; mappings?: unknown },
    variables: Record<string, any> | undefined
): string[] {
    const referenced = new Set<string>()
    collectReferences(config.inputs, referenced)
    collectReferences(config.mappings, referenced)

    const available = variables ?? {}
    return [...referenced].filter((name) => !(name in available)).sort()
}

/**
 * Warn (run log + operational log + metric) when a step is about to render inputs referencing
 * variables the run does not have. Detection only - rendering is unchanged.
 */
export function observeMissingVariableReferences(
    invocation: CyclotronJobInvocationHogFlow,
    action: HogFlowAction,
    result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>
): void {
    const missing = findMissingVariableReferences(
        action.config as { inputs?: unknown; mappings?: unknown },
        invocation.state.variables
    )
    if (missing.length === 0) {
        return
    }

    result.logs.push({
        level: 'warn',
        timestamp: DateTime.now(),
        message: `${actionIdForLogging(action)} References variable(s) that are not set for this run: ${missing.join(', ')}. They will render empty.`,
    })
    logger.warn('[HogFlowVariableUsage] Step references variables the run does not have', {
        teamId: invocation.teamId,
        hogFlowId: invocation.hogFlow.id,
        actionId: action.id,
        missing,
    })
    counterMissingVariableReference.labels({ hog_flow_id: invocation.hogFlow.id }).inc()
}
