import { ROOT_CONTEXT, TraceFlags, context, propagation, trace } from '@opentelemetry/api'
import { InMemorySpanExporter, NodeTracerProvider, SimpleSpanProcessor } from '@opentelemetry/sdk-trace-node'
import { register } from 'prom-client'

import * as posthogUtils from '~/common/utils/posthog'

import { instrumentFn, startDetachedSpan } from './tracing-utils'

describe('instrumentFn', () => {
    let exporter: InMemorySpanExporter
    let provider: NodeTracerProvider

    beforeEach(() => {
        exporter = new InMemorySpanExporter()
        provider = new NodeTracerProvider({ spanProcessors: [new SimpleSpanProcessor(exporter)] })
        provider.register()
    })

    afterEach(async () => {
        await provider.shutdown()
        trace.disable()
        context.disable()
        propagation.disable()
    })

    it('emits no span when span is false but still records the duration summary', async () => {
        await expect(
            instrumentFn({ key: 'no_span', tag: 'tagged', span: false }, () => Promise.resolve('ok'))
        ).resolves.toBe('ok')

        expect(exporter.getFinishedSpans()).toEqual([])
        const summary = await register.getSingleMetric('instrumented_fn_duration_ms')!.get()
        expect(summary.values).toContainEqual({
            metricName: 'instrumented_fn_duration_ms_count',
            labels: { metricName: 'no_span', tag: 'tagged' },
            value: 1,
        })
    })

    it('parents the span on parentContext instead of the active context', async () => {
        const batch = startDetachedSpan('batch', {})!

        await trace.getTracer('test').startActiveSpan('unrelated', async (unrelated) => {
            await instrumentFn({ key: 'step', parentContext: batch.parentContext }, () => Promise.resolve())
            unrelated.end()
        })
        batch.span.end()

        const byName = Object.fromEntries(exporter.getFinishedSpans().map((span) => [span.name, span]))
        expect(Object.keys(byName).sort()).toEqual(['batch', 'step', 'unrelated'])
        expect(byName.step.parentSpanContext?.spanId).toBe(byName.batch.spanContext().spanId)
    })

    it('runs work under an unsampled parentContext inside that context, so nested spans stay unsampled', async () => {
        const unsampledParent = trace.setSpanContext(ROOT_CONTEXT, {
            traceId: '0af7651916cd43dd8448eb211c80319c',
            spanId: 'b7ad6b7169203331',
            traceFlags: TraceFlags.NONE,
        })

        await instrumentFn({ key: 'step', parentContext: unsampledParent }, () =>
            trace.getTracer('test').startActiveSpan('nested', (nested) => {
                nested.end()
                return Promise.resolve()
            })
        )

        expect(exporter.getFinishedSpans()).toEqual([])
    })

    it('captures a failure while its span is active, so the error carries its trace id', async () => {
        let activeSpanIdAtCapture: string | undefined
        jest.spyOn(posthogUtils, 'captureException').mockImplementationOnce(() => {
            activeSpanIdAtCapture = trace.getActiveSpan()?.spanContext().spanId
        })

        await expect(instrumentFn('failing_step', () => Promise.reject(new Error('boom')))).rejects.toThrow('boom')

        const [span] = exporter.getFinishedSpans()
        expect(activeSpanIdAtCapture).toBe(span.spanContext().spanId)
    })
})
