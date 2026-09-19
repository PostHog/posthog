import { metrics } from '@opentelemetry/api'
import { DateTime } from 'luxon'
import { z } from 'zod'

import { createCounterWithExemplars, createHistogramWithExemplars, swallowing } from '~/common/metrics/instruments'
import { captureException } from '~/common/utils/posthog'
import { fetch } from '~/common/utils/request'

import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '../types'
import { createInvocationResult } from '../utils/invocation-utils'
import type { TransformationExecutionOptions } from './hog-transformer.service'

const configSchema = z.object({
    api_key: z.string().min(1),
    property: z.string().min(1),
    instructions: z.string().min(1),
    categories: z
        .record(z.string().min(1), z.string().min(1))
        .refine((categories) => Object.keys(categories).length > 0),
    excluded_properties: z.array(z.string()),
    minimum_confidence: z.number().min(0).max(1),
})

const recordCall = swallowing((outcome: 'success' | 'failure', durationMs: number): void => {
    // Acquire the meter after service startup so it uses the configured metrics exporter.
    const meter = metrics.getMeter('cdp')
    createCounterWithExemplars(meter, 'cdp.typesafe.calls').add(1, { outcome })
    createHistogramWithExemplars(meter, 'cdp.typesafe.call.duration', { unit: 'ms' }).record(durationMs, { outcome })
})

const reportCallError = swallowing(
    (message: string, failureKind: 'request' | 'http' | 'invalid_response', httpStatus?: number): void => {
        // Provider errors can contain credentials or event data. Do not attach the original error.
        captureException(new Error(message), {
            tags: { template_id: 'native-typesafe', failure_kind: failureKind },
            extra: httpStatus === undefined ? {} : { http_status: httpStatus },
        })
    }
)

function excludeProperties(value: unknown, excluded: Set<string>, path = ''): unknown {
    if (Array.isArray(value)) {
        return value.map((item) => excludeProperties(item, excluded, path))
    }
    if (value !== null && typeof value === 'object') {
        return Object.fromEntries(
            Object.entries(value)
                .filter(([key]) => !excluded.has(key.toLowerCase()) && !excluded.has(`${path}${key}`.toLowerCase()))
                .map(([key, child]) => [key, excludeProperties(child, excluded, `${path}${key}.`)])
        )
    }
    return value
}

export async function executeTypesafeTransformation(
    invocation: CyclotronJobInvocationHogFunction,
    options?: TransformationExecutionOptions
): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
    const event = invocation.state.globals.event
    const result = createInvocationResult<CyclotronJobInvocationHogFunction>(invocation, {}, { execResult: event })
    const log = (level: 'info' | 'warn' | 'error', message: string): void => {
        result.logs.push({ level, message, timestamp: DateTime.now() })
    }
    // Monitoring persists logs and a pass/fail count, but not result.error, so a failure needs a
    // log for the user to see the reason.
    const fail = (message: string): void => {
        result.error = message
        log('error', message)
    }
    const parsed = configSchema.safeParse(invocation.state.globals.inputs)
    if (!parsed.success) {
        fail('Invalid TypeSafe settings. Check the required inputs.')
        return result
    }
    const config = parsed.data
    const properties = event.properties ?? {}
    if (Object.hasOwn(properties, config.property)) {
        return result
    }
    // The caller asked for simulated async calls, so the event and the key must not leave PostHog.
    if (options?.mockAsyncFunctions) {
        log('info', 'TypeSafe request mocked. Event unchanged. Turn off mocking to send a real request.')
        return result
    }

    let requestStarted: number | undefined
    let failureKind: 'request' | 'http' | 'invalid_response' = 'request'
    let httpStatus: number | undefined
    try {
        const excluded = new Set([...config.excluded_properties, config.property].map((key) => key.toLowerCase()))
        const body = JSON.stringify({
            model: 'jev-1.13.0',
            state: { event: event.event, properties: excludeProperties(properties, excluded) },
            questions: {
                category: {
                    type: 'choice',
                    instructions: config.instructions,
                    criteria: config.categories,
                },
            },
        })
        if (Buffer.byteLength(body) > 16_000) {
            log('warn', 'TypeSafe input exceeds 16 KB. Event unchanged. Exclude more properties.')
            return result
        }

        // This local prototype waits here because the transformation must return the enriched event.
        requestStarted = performance.now()
        const response = await fetch('https://api.typesafe.ai/v1/systemone', {
            method: 'POST',
            headers: { Authorization: `Bearer ${config.api_key}`, 'Content-Type': 'application/json' },
            body,
            timeoutMs: 3000,
        })
        httpStatus = response.status
        if (response.status < 200 || response.status >= 300) {
            failureKind = 'http'
            fail(`TypeSafe request failed with status ${response.status}. Event unchanged.`)
            // A failed body read must not reach the catch below and replace the status error.
            await response.dump().catch(() => undefined)
            return result
        }
        failureKind = 'invalid_response'
        const responseBody = (await response.json()) as {
            answers?: { category?: { type?: string; choice?: string; confidence?: number } }
        }
        const answer = responseBody?.answers?.category
        if (
            answer?.type !== 'choice' ||
            typeof answer.choice !== 'string' ||
            !Object.hasOwn(config.categories, answer.choice) ||
            typeof answer.confidence !== 'number' ||
            !Number.isFinite(answer.confidence) ||
            answer.confidence < 0 ||
            answer.confidence > 1
        ) {
            fail('TypeSafe returned an invalid answer. Event unchanged.')
            return result
        }
        if (answer.confidence < config.minimum_confidence) {
            log('warn', 'TypeSafe returned an uncertain answer. Event unchanged.')
            return result
        }
        result.execResult = { ...event, properties: { ...properties, [config.property]: answer.choice } }
        log('info', 'TypeSafe added the category to the event.')
    } catch {
        fail(
            failureKind === 'invalid_response'
                ? 'TypeSafe returned an invalid answer. Event unchanged.'
                : 'TypeSafe request failed. Event unchanged. Check the API key and connection.'
        )
    } finally {
        if (requestStarted !== undefined) {
            const durationMs = performance.now() - requestStarted
            result.invocation.state.timings.push({ kind: 'async_function', duration_ms: durationMs })
            recordCall(result.error ? 'failure' : 'success', durationMs)
            if (result.error) {
                reportCallError(result.error, failureKind, httpStatus)
            }
        }
    }
    return result
}
