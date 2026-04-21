import { register } from 'prom-client'

import { createTestEventHeaders } from '../../../tests/helpers/event-headers'
import { createTestMessage } from '../../../tests/helpers/kafka-message'
import { INGESTION_LAG_INDICATOR, INGESTION_LATENCY_GROUP } from '../common/slas'
import { IngestionSlaBuilder } from '../slas/builder'
import { createReportSlisStep } from './report-slis-step'

describe('reportSlisStep', () => {
    const FAKE_NOW_MS = 1702654321987

    beforeEach(() => {
        register.clear()
        jest.useFakeTimers()
        jest.setSystemTime(FAKE_NOW_MS)
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    function buildStep() {
        const slas = new IngestionSlaBuilder()
            .group(INGESTION_LATENCY_GROUP, (latency) =>
                latency.indicator(INGESTION_LAG_INDICATOR, (ingestionLag) =>
                    ingestionLag.objective('under_5s', { thresholdMs: 5000, targetRatio: 0.999 })
                )
            )
            .build({ pipeline: 'ingestion', lane: 'main' })
        return createReportSlisStep(slas.indicator(INGESTION_LAG_INDICATOR))
    }

    it('observes lag when now header and partition are present', async () => {
        const step = buildStep()
        const input = {
            headers: createTestEventHeaders({ now: new Date(FAKE_NOW_MS - 4500) }),
            message: createTestMessage({ partition: 3 }),
        }

        await step(input)

        const out = await register.getSingleMetricAsString(INGESTION_LATENCY_GROUP.name)
        expect(out).toMatch(
            /_bucket\{[^}]*le="5000"[^}]*sli="ingestion_lag"[^}]*\} 1|_bucket\{[^}]*sli="ingestion_lag"[^}]*le="5000"[^}]*\} 1/
        )
    })

    it('terminates in void', async () => {
        const step = buildStep()
        const input = {
            headers: createTestEventHeaders({ now: new Date(FAKE_NOW_MS - 1000) }),
            message: createTestMessage(),
        }

        const result = await step(input)

        expect(result.type).toBe(0) // OK
        if (result.type === 0) {
            expect(result.value).toBeUndefined()
        }
    })

    it('is a no-op when the now header is missing', async () => {
        const step = buildStep()
        const input = {
            headers: createTestEventHeaders(),
            message: createTestMessage(),
        }

        await step(input)

        const out = await register.getSingleMetricAsString(INGESTION_LATENCY_GROUP.name)
        expect(out).not.toMatch(/_count\{[^}]*\} [1-9]/)
    })

    it('is a no-op when partition is undefined', async () => {
        const step = buildStep()
        const input = {
            headers: createTestEventHeaders({ now: new Date(FAKE_NOW_MS - 1000) }),
            message: createTestMessage({ partition: undefined as unknown as number }),
        }

        await step(input)

        const out = await register.getSingleMetricAsString(INGESTION_LATENCY_GROUP.name)
        expect(out).not.toMatch(/_count\{[^}]*\} [1-9]/)
    })

    it('handles partition 0', async () => {
        const step = buildStep()
        const input = {
            headers: createTestEventHeaders({ now: new Date(FAKE_NOW_MS - 500) }),
            message: createTestMessage({ partition: 0 }),
        }

        await step(input)

        const out = await register.getSingleMetricAsString(INGESTION_LATENCY_GROUP.name)
        expect(out).toMatch(
            /_bucket\{[^}]*le="1000"[^}]*sli="ingestion_lag"[^}]*\} 1|_bucket\{[^}]*sli="ingestion_lag"[^}]*le="1000"[^}]*\} 1/
        )
    })
})
