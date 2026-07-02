import { convertHogToJS } from '@posthog/hogvm'

import type { HogFunctionType } from '~/cdp/types'
import { sanitizeLogMessage } from '~/cdp/utils'
import { execHogImmediate } from '~/cdp/utils/hog-exec'
import { parseJSON } from '~/common/utils/json-parse'

import type { LogRecord } from '../log-record-avro'

// Per-record execution primitives for log transformations. Pure functions, no I/O:
// orchestration (function fetching, budgets, monitoring) lives in the transformer service.

/** Hard per-record VM kill. ~100x the p99 of realistic scrub programs (see benchmarks/). */
export const DEFAULT_LOG_TRANSFORMATION_TIMEOUT_MS = 10

/** Log records are ~1KB; transformations have no business allocating anywhere near this. */
export const LOG_TRANSFORMATION_MEMORY_LIMIT_BYTES = 8 * 1024 * 1024

/** Max captured print() entries per invocation — far lower than destinations' 25,
 * since a transformation can run hundreds of thousands of times per second. */
export const MAX_LOG_TRANSFORMATION_PRINT_LOGS = 5

export interface LogTransformationGlobals {
    project: { id: number; name: string; url: string }
    record: {
        body: string | null
        attributes: Record<string, string>
        resource_attributes: Record<string, string>
        severity_text: string | null
        severity_number: number | null
        service_name: string | null
        instrumentation_scope: string | null
        event_name: string | null
        timestamp: number | null
        observed_timestamp: number | null
        trace_id: string | null
        span_id: string | null
    }
    inputs: Record<string, unknown>
}

export type LogTransformationOutcome =
    | { status: 'mutated'; durationMs: number; logs: string[] }
    | { status: 'dropped'; durationMs: number; logs: string[] }
    | { status: 'failed'; durationMs: number; logs: string[]; error: string }

export function buildLogRecordGlobals(
    record: LogRecord,
    project: LogTransformationGlobals['project'],
    inputs: Record<string, unknown>
): LogTransformationGlobals {
    return {
        project,
        record: {
            body: record.body ?? null,
            attributes: decodeAttributeMap(record.attributes),
            resource_attributes: decodeAttributeMap(record.resource_attributes),
            severity_text: record.severity_text ?? null,
            severity_number: record.severity_number ?? null,
            service_name: record.service_name ?? null,
            instrumentation_scope: record.instrumentation_scope ?? null,
            event_name: record.event_name ?? null,
            timestamp: record.timestamp ?? null,
            observed_timestamp: record.observed_timestamp ?? null,
            trace_id: record.trace_id ? record.trace_id.toString('hex') : null,
            span_id: record.span_id ? record.span_id.toString('hex') : null,
        },
        inputs,
    }
}

/**
 * Attribute values arrive JSON-encoded from capture (`any_value_to_json`): a string
 * attribute is stored as `"error"` (with quotes), a number as `123`. The ClickHouse
 * sink decodes string values with `JSONExtractString`, so that is what users see in
 * the Logs UI. Transformations must see the same decoded values — otherwise
 * `record.attributes['level'] == 'error'` silently never matches.
 */
export function decodeLogAttributeValue(value: string): string {
    if (value.length >= 2 && value.startsWith('"') && value.endsWith('"')) {
        try {
            const parsed = parseJSON(value)
            if (typeof parsed === 'string') {
                return parsed
            }
        } catch {
            // Not valid JSON — treat as a plain string
        }
    }
    return value
}

/**
 * Inverse of `decodeLogAttributeValue` for values written back onto the record:
 * plain strings are JSON-encoded so the ClickHouse sink's `JSONExtractString`
 * surfaces them; values that are already valid JSON (numbers, booleans, objects,
 * pre-encoded strings) pass through unchanged.
 */
export function encodeLogAttributeValue(value: string): string {
    try {
        parseJSON(value)
        return value
    } catch {
        return JSON.stringify(value)
    }
}

function decodeAttributeMap(map: Record<string, string> | null | undefined): Record<string, string> {
    const out: Record<string, string> = {}
    for (const [key, value] of Object.entries(map ?? {})) {
        out[key] = decodeLogAttributeValue(value)
    }
    return out
}

/**
 * Encodes a decoded attribute map back to the wire form. Values the transformation left
 * untouched keep their exact original wire encoding — the decode/encode pair is lossy for
 * string values that look like JSON scalars ('"3"' decodes to '3', which re-encodes as the
 * number 3), so round-tripping through the original is the only faithful option.
 */
function encodeAttributeMap(
    map: Record<string, string>,
    original: Record<string, string> | null | undefined
): Record<string, string> {
    const out: Record<string, string> = {}
    for (const [key, value] of Object.entries(map)) {
        const originalValue = original?.[key]
        if (originalValue !== undefined && decodeLogAttributeValue(originalValue) === value) {
            out[key] = originalValue
        } else {
            out[key] = encodeLogAttributeValue(value)
        }
    }
    return out
}

function coerceStringMap(value: unknown): Record<string, string> | null {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        return null
    }
    const result: Record<string, string> = {}
    for (const [key, entry] of Object.entries(value as Record<string, unknown>)) {
        if (entry === null || entry === undefined) {
            continue
        }
        result[key] = typeof entry === 'string' ? entry : JSON.stringify(entry)
    }
    return result
}

/**
 * Merges a transformation's return value back into the record, in place.
 *
 * Only `body`, `attributes`, `severity_text`, and `resource_attributes` are writable.
 * Timestamps, trace/span ids, service identity, and `bytes_uncompressed` are read-only:
 * billing bytes are computed at capture time, and scrubbing must never change what a
 * customer is billed.
 *
 * Returns 'invalid' (record untouched) when the result is not record-shaped — the
 * caller treats that as a failure and fails open.
 */
export function applyTransformResult(record: LogRecord, execResult: unknown): 'mutated' | 'dropped' | 'invalid' {
    if (execResult === null || execResult === undefined || execResult === false) {
        return 'dropped'
    }

    if (typeof execResult !== 'object' || Array.isArray(execResult)) {
        return 'invalid'
    }

    const result = execResult as Record<string, unknown>

    // Validate everything before mutating anything, so an invalid result leaves the
    // record fully untouched rather than half-applied.
    let body: string | null | undefined = undefined
    if ('body' in result) {
        if (result.body !== null && typeof result.body !== 'string') {
            return 'invalid'
        }
        body = result.body
    }

    let severityText: string | null | undefined = undefined
    if ('severity_text' in result) {
        if (result.severity_text !== null && typeof result.severity_text !== 'string') {
            return 'invalid'
        }
        severityText = result.severity_text
    }

    // Like `body`, an explicit null clears the field; an absent key leaves it untouched.
    let attributes: Record<string, string> | null | undefined = undefined
    if ('attributes' in result) {
        if (result.attributes === null) {
            attributes = null
        } else {
            attributes = coerceStringMap(result.attributes)
            if (attributes === null) {
                return 'invalid'
            }
        }
    }

    let resourceAttributes: Record<string, string> | null | undefined = undefined
    if ('resource_attributes' in result) {
        if (result.resource_attributes === null) {
            resourceAttributes = null
        } else {
            resourceAttributes = coerceStringMap(result.resource_attributes)
            if (resourceAttributes === null) {
                return 'invalid'
            }
        }
    }

    if (body !== undefined) {
        record.body = body
    }
    if (severityText !== undefined) {
        record.severity_text = severityText
    }
    if (attributes !== undefined) {
        record.attributes = attributes === null ? null : encodeAttributeMap(attributes, record.attributes)
    }
    if (resourceAttributes !== undefined) {
        record.resource_attributes =
            resourceAttributes === null ? null : encodeAttributeMap(resourceAttributes, record.resource_attributes)
    }

    return 'mutated'
}

/**
 * Resolves a function's input values against log globals. Inputs may reference earlier
 * inputs, so resolution happens in declared order; hog-templated inputs execute their
 * compiled bytecode with the accumulated `inputs` visible.
 *
 * Throws on the first unresolvable input — callers decide the failure policy
 * (the pipeline fails open per record; the test-invocation API surfaces the error).
 */
export function resolveLogTransformationInputs(
    fn: Pick<HogFunctionType, 'inputs' | 'encrypted_inputs'>,
    globals: Omit<LogTransformationGlobals, 'inputs'>,
    timeoutMs: number
): { inputs: Record<string, unknown>; durationMs: number } {
    const inputs: Record<string, unknown> = {}
    const allInputs = { ...fn.inputs, ...fn.encrypted_inputs }
    // VM time spent on templates counts toward the same budgets as the code body —
    // record-referencing templates run per record and would otherwise bypass them.
    let durationMs = 0

    const entries = Object.entries(allInputs).sort(([, a], [, b]) => (a?.order ?? -1) - (b?.order ?? -1))

    for (const [key, input] of entries) {
        if (input?.bytecode && (input.templating ?? 'hog') === 'hog') {
            const {
                execResult,
                error,
                durationMs: execMs,
            } = execHogImmediate(input.bytecode, {
                globals: { ...globals, inputs },
                timeout: timeoutMs,
                maxAsyncSteps: 0,
            })
            durationMs += execMs
            if (error || execResult?.error || !execResult?.finished) {
                throw new Error(`Could not resolve input '${key}': ${error ?? execResult?.error}`)
            }
            inputs[key] = execResult.result
        } else {
            inputs[key] = input?.value
        }
    }

    return { inputs, durationMs }
}

export interface ExecuteLogTransformationOptions {
    timeoutMs?: number
    /** Values redacted from captured print() output (e.g. secret input values). */
    sensitiveValues?: string[]
}

/**
 * Runs one compiled transformation against one record's globals and merges the result
 * into the record in place. Synchronous and CPU-only: no async functions are registered,
 * so customer code cannot perform I/O.
 */
export function executeLogTransformation(
    bytecode: unknown,
    record: LogRecord,
    globals: LogTransformationGlobals,
    options: ExecuteLogTransformationOptions = {}
): LogTransformationOutcome {
    const timeoutMs = options.timeoutMs ?? DEFAULT_LOG_TRANSFORMATION_TIMEOUT_MS
    const logs: string[] = []

    const { execResult, error, durationMs } = execHogImmediate(bytecode, {
        globals,
        timeout: timeoutMs,
        maxAsyncSteps: 0,
        memoryLimit: LOG_TRANSFORMATION_MEMORY_LIMIT_BYTES,
        functions: {
            print: (...args: unknown[]) => {
                if (logs.length < MAX_LOG_TRANSFORMATION_PRINT_LOGS) {
                    logs.push(sanitizeLogMessage(args, options.sensitiveValues))
                }
            },
        },
    })

    if (error || execResult?.error) {
        return { status: 'failed', durationMs, logs, error: String(error ?? execResult?.error) }
    }

    if (!execResult?.finished) {
        // With no async functions registered the VM always runs to completion or throws;
        // a paused VM here means a bug, not customer error. Treat as failure (fail-open).
        return { status: 'failed', durationMs, logs, error: 'VM did not finish execution' }
    }

    const converted = convertHogToJS(execResult.result)
    const applied = applyTransformResult(record, converted)

    if (applied === 'invalid') {
        return {
            status: 'failed',
            durationMs,
            logs,
            error: 'Transformation must return the record (optionally mutated) or null to drop it',
        }
    }

    if (applied === 'dropped') {
        return { status: 'dropped', durationMs, logs }
    }

    return { status: 'mutated', durationMs, logs }
}
