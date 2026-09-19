import { metrics } from '@opentelemetry/api'
import { InMemoryMetricExporter, MeterProvider, PeriodicExportingMetricReader } from '@opentelemetry/sdk-metrics'

import { parseJSON } from '~/common/utils/json-parse'
import { captureException } from '~/common/utils/posthog'
import { FetchResponse, fetch } from '~/common/utils/request'

import { createExampleInvocation } from '../_tests/fixtures'
import { template } from '../templates/_transformations/typesafe/typesafe.template'
import { CyclotronJobInvocationHogFunction } from '../types'
import type { TransformationExecutionOptions } from './hog-transformer.service'
import { executeTypesafeTransformation, typesafeAnswerCache } from './typesafe'

jest.mock('~/common/utils/request', () => ({ fetch: jest.fn() }))
jest.mock('~/common/utils/posthog', () => ({ captureException: jest.fn() }))

function mockResponse(category: unknown, status = 200): FetchResponse {
    return {
        status,
        headers: {},
        json: () => Promise.resolve({ answers: { category } }),
        text: () => Promise.resolve(''),
        dump: () => Promise.resolve(),
    }
}

describe('TypeSafe transformation', () => {
    const request = jest.mocked(fetch)
    const captureError = jest.mocked(captureException)
    let provider: MeterProvider
    let exporter: InMemoryMetricExporter

    const expectCallMetrics = async (outcome: 'success' | 'failure', count = 1, durationMs = 0): Promise<void> => {
        jest.useRealTimers()
        await provider.forceFlush()
        const recorded = exporter
            .getMetrics()
            .flatMap((resource) => resource.scopeMetrics.flatMap((scope) => scope.metrics))
        expect(recorded).toEqual(
            expect.arrayContaining([
                expect.objectContaining({
                    descriptor: expect.objectContaining({ name: 'cdp.typesafe.calls' }),
                    dataPoints: [expect.objectContaining({ attributes: { outcome }, value: count })],
                }),
                expect.objectContaining({
                    descriptor: expect.objectContaining({ name: 'cdp.typesafe.call.duration', unit: 'ms' }),
                    dataPoints: [
                        expect.objectContaining({
                            attributes: { outcome },
                            value: expect.objectContaining({ count, sum: durationMs }),
                        }),
                    ],
                }),
            ])
        )
    }

    const expectNoCallTelemetry = async (): Promise<void> => {
        jest.useRealTimers()
        await provider.forceFlush()
        expect(exporter.getMetrics()).toEqual([])
        expect(captureError).not.toHaveBeenCalled()
    }
    const createInvocation = (): CyclotronJobInvocationHogFunction =>
        createExampleInvocation(
            { type: 'transformation', template_id: template.id },
            {
                inputs: {
                    ...Object.fromEntries(template.inputs_schema.map((input) => [input.key, input.default])),
                    api_key: 'fake-demo-key',
                    excluded_properties: ['debug_blob', 'email', 'metadata.private'],
                },
                event: {
                    uuid: 'demo-event',
                    event: 'demo article viewed',
                    distinct_id: 'demo-reader',
                    elements_chain: '',
                    url: '',
                    timestamp: '',
                    properties: {
                        title: 'Watercolor painting',
                        email: 'reader@example.com',
                        debug_blob: 'x'.repeat(20_000),
                        metadata: { private: 'omitted', visible: 'included', items: [{ email: 'reader@example.com' }] },
                    },
                },
            }
        )

    beforeEach(() => {
        jest.useFakeTimers()
        request.mockReset()
        captureError.mockReset()
        typesafeAnswerCache.clear()
        exporter = new InMemoryMetricExporter(0)
        provider = new MeterProvider({
            readers: [new PeriodicExportingMetricReader({ exporter, exportIntervalMillis: 60_000 })],
        })
        metrics.setGlobalMeterProvider(provider)
    })

    afterEach(async () => {
        jest.useRealTimers()
        await provider.shutdown()
        metrics.disable()
    })

    it('adds a category while exclusions affect only the model input', async () => {
        const invocation = createInvocation()
        const event = invocation.state.globals.event
        request.mockImplementation(() => {
            jest.advanceTimersByTime(75)
            return Promise.resolve({
                ...mockResponse(null),
                json: () => {
                    jest.advanceTimersByTime(25)
                    return Promise.resolve({
                        answers: { category: { type: 'choice', choice: 'art', confidence: 0.95 } },
                    })
                },
            })
        })
        const result = await executeTypesafeTransformation(invocation)
        expect(result).toMatchObject({
            finished: true,
            execResult: { ...event, properties: { ...event.properties, content_category: 'art' } },
        })
        expect(result.error).toBeUndefined()
        expect(parseJSON(request.mock.calls[0][1]?.body as string).state).toEqual({
            event: 'demo article viewed',
            properties: { title: 'Watercolor painting', metadata: { visible: 'included', items: [{}] } },
        })
        expect(event.properties).not.toHaveProperty('content_category')
        await expectCallMetrics('success', 1, 100)
        expect(captureError).not.toHaveBeenCalled()
    })

    it('answers a repeated input from the cache and keys the cache by transformation', async () => {
        request.mockResolvedValue(mockResponse({ type: 'choice', choice: 'art', confidence: 0.95 }))
        const invocation = createInvocation()
        await executeTypesafeTransformation(invocation)
        const cached = await executeTypesafeTransformation(invocation)
        expect(cached).toMatchObject({
            execResult: { properties: expect.objectContaining({ content_category: 'art' }) },
            logs: [
                expect.objectContaining({ level: 'info', message: expect.stringContaining('cache') }),
                expect.objectContaining({ level: 'info', message: 'TypeSafe added the category to the event.' }),
            ],
        })
        expect(request).toHaveBeenCalledTimes(1)

        const otherTransformation = createInvocation()
        otherTransformation.hogFunction.id = 'another-transformation'
        await executeTypesafeTransformation(otherTransformation)
        expect(request).toHaveBeenCalledTimes(2)
        await expectCallMetrics('success', 2)
    })

    it.each<{ properties?: Record<string, any>; options?: TransformationExecutionOptions }>([
        { properties: { content_category: 'existing' } },
        { properties: { title: 'x'.repeat(20_000) } },
        { options: { mockAsyncFunctions: true } },
    ])('does not call the model for classified, oversized, or mocked events', async ({ properties, options }) => {
        const invocation = createInvocation()
        if (properties) {
            invocation.state.globals.event.properties = properties
        }
        expect(await executeTypesafeTransformation(invocation, options)).toMatchObject({
            execResult: invocation.state.globals.event,
        })
        expect(request).not.toHaveBeenCalled()
        await expectNoCallTelemetry()
    })

    it.each([
        [{ type: 'choice', choice: 'art', confidence: 0.2 }, false],
        [{ type: 'choice', choice: 'invalid', confidence: 0.95 }, true],
        [{ type: 'choice', choice: 'art' }, true],
    ])('keeps the event when the answer is uncertain or invalid', async (category, failed) => {
        const invocation = createInvocation()
        request.mockResolvedValue(mockResponse(category))
        const result = await executeTypesafeTransformation(invocation)
        expect(result).toMatchObject({
            execResult: invocation.state.globals.event,
        })
        await expectCallMetrics(failed ? 'failure' : 'success')
        if (failed) {
            expect(result.error).toContain('invalid answer')
            expect(captureError).toHaveBeenCalledTimes(1)
            expect(captureError).toHaveBeenCalledWith(expect.any(Error), {
                tags: { template_id: 'native-typesafe', failure_kind: 'invalid_response' },
                extra: { http_status: 200 },
            })
        } else {
            expect(result.error).toBeUndefined()
            expect(result.logs).toEqual([expect.objectContaining({ level: 'warn' })])
            expect(captureError).not.toHaveBeenCalled()
        }
    })

    it('keeps events and reports failures without exposing the key', async () => {
        const invocation = createInvocation()
        request.mockRejectedValueOnce(new Error('Request failed for fake-demo-key'))
        request.mockResolvedValueOnce({
            ...mockResponse(null, 429),
            dump: () => Promise.reject(new Error('Socket closed while reading fake-demo-key response')),
        })
        request.mockResolvedValueOnce({
            ...mockResponse(null),
            json: () => Promise.reject(new SyntaxError('Invalid JSON containing fake-demo-key and reader@example.com')),
        })
        for (const expectedError of ['Check the API key', 'status 429', 'invalid answer']) {
            const result = await executeTypesafeTransformation(invocation)
            expect(result).toMatchObject({ finished: true, execResult: invocation.state.globals.event })
            expect(result.error).toContain(expectedError)
            expect(result.error).not.toContain('fake-demo-key')
            // Monitoring drops result.error, so the reason only reaches the user as a log.
            expect(result.logs).toEqual([expect.objectContaining({ level: 'error', message: result.error })])
        }
        await expectCallMetrics('failure', 3)
        expect(captureError).toHaveBeenCalledTimes(3)
        expect(captureError.mock.calls.map(([, hint]) => hint?.tags?.failure_kind)).toEqual([
            'request',
            'http',
            'invalid_response',
        ])
        for (const [error, hint] of captureError.mock.calls) {
            expect(error.cause).toBeUndefined()
            expect(JSON.stringify({ message: error.message, stack: error.stack, hint })).not.toMatch(
                /fake-demo-key|reader@example.com|Watercolor painting/
            )
        }
    })

    it.each([{ minimum_confidence: -1 }, { api_key: '' }])(
        'rejects invalid settings without making a request',
        async (inputs) => {
            const invocation = createInvocation()
            Object.assign(invocation.state.globals.inputs, inputs)
            expect(await executeTypesafeTransformation(invocation)).toMatchObject({
                execResult: invocation.state.globals.event,
                error: expect.stringContaining('Invalid TypeSafe settings'),
                logs: [
                    expect.objectContaining({
                        level: 'error',
                        message: expect.stringContaining('Invalid TypeSafe settings'),
                    }),
                ],
            })
            expect(request).not.toHaveBeenCalled()
            await expectNoCallTelemetry()
        }
    )

    it('uses the key configured on each transformation', async () => {
        request.mockResolvedValue(mockResponse({ type: 'choice', choice: 'art', confidence: 0.95 }))
        for (const apiKey of ['fake-key-one', 'fake-key-two']) {
            const invocation = createInvocation()
            invocation.hogFunction.id = `transformation-with-${apiKey}`
            invocation.state.globals.inputs.api_key = apiKey
            await executeTypesafeTransformation(invocation)
            expect(request).toHaveBeenLastCalledWith(
                'https://api.typesafe.ai/v1/systemone',
                expect.objectContaining({
                    headers: expect.objectContaining({ Authorization: `Bearer ${apiKey}` }),
                    timeoutMs: 1000,
                })
            )
        }
    })
})
