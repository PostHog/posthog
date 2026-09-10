import { DateTime } from 'luxon'
import { Counter, Histogram } from 'prom-client'

import { HogFlowAction } from '~/cdp/schema/hogflow'
import { CyclotronJobInvocationHogFlow, CyclotronJobInvocationResult } from '~/cdp/types'
import { logger } from '~/common/utils/logger'

import { actionIdForLogging } from './hogflow-utils'

// Deliberately unlabelled: the metric answers "how common are variable misses fleet-wide" (it
// sizes the publish-time lint work); which flow/step/variable missed is in the warn log, where
// unbounded cardinality belongs.
const counterMissingVariableReference = new Counter({
    name: 'cdp_hogflow_missing_variable_reference',
    help: 'A workflow step referenced a variable that is not set for the run, so it renders empty',
})

// The scan runs on every fresh entry into a function step, so its cost has to stay observable.
const histogramVariableScanDuration = new Histogram({
    name: 'cdp_hogflow_variable_scan_duration_seconds',
    help: 'Time spent scanning a step config for workflow variable references',
    buckets: [0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5],
})

// Both templating modes reference workflow variables textually: `{variables.foo}` (hog) and
// `{{ variables.foo }}` (liquid), plus the bracket form `variables['my-var']`.  A regex scan over
// the raw template strings covers both without parsing either language.
const DOT_REFERENCE_REGEX = /\bvariables\.([A-Za-z_$][A-Za-z0-9_$]*)/g
// Whitespace allowed around the brackets and quotes - liquid accepts `variables[ 'x' ]`
const BRACKET_REFERENCE_REGEX = /\bvariables\s*\[\s*['"]([^'"\]]+)['"]\s*\]/g

// Compiled hog output carried alongside the template strings. Never scanned: it's by far the
// bulkiest part of a config (hundreds of elements per input), references in it are stored as
// separate string constants that can't match the regexes, and a liquid/template string embedded
// verbatim as a bytecode constant would be a false positive - the executor renders from the
// template, not from that constant.
const SKIPPED_KEYS = new Set(['bytecode', 'transpiled'])

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
        Object.entries(value).forEach(([key, item]) => {
            if (!SKIPPED_KEYS.has(key)) {
                collectReferences(item, into)
            }
        })
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
    const stopTimer = histogramVariableScanDuration.startTimer()
    const missing = findMissingVariableReferences(
        action.config as { inputs?: unknown; mappings?: unknown },
        invocation.state.variables
    )
    stopTimer()
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
    counterMissingVariableReference.inc()
}
