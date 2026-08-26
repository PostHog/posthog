import type { Counter } from 'prom-client'

import { DEFAULT_PATTERN_MAX_INPUT_CHARS } from './config'
import {
    logsPatternBodyKindCounter,
    logsPatternInputCappedCounter,
    logsPatternRuleFiredCounter,
    logsPatternStageErrorCounter,
    makePatternMaskingStage,
} from './log-pattern-stage'
import type { LogRecord } from './log-record-avro'

const makeRecord = (body: string | null): LogRecord => ({
    uuid: null,
    trace_id: null,
    span_id: null,
    trace_flags: null,
    timestamp: null,
    observed_timestamp: null,
    body,
    severity_text: null,
    severity_number: null,
    service_name: null,
    resource_attributes: null,
    instrumentation_scope: null,
    event_name: null,
    attributes: null,
})

describe('log-pattern-stage', () => {
    beforeEach(() => {
        logsPatternBodyKindCounter.reset()
        logsPatternRuleFiredCounter.reset()
        logsPatternInputCappedCounter.reset()
        logsPatternStageErrorCounter.reset()
    })

    const counterValues = async (counter: Counter<string>): Promise<Record<string, number>> => {
        const metric = await counter.get()
        return Object.fromEntries(metric.values.map((v) => [Object.values(v.labels)[0] ?? '', v.value]))
    }

    it('tallies body kinds, rule fires, and input caps across a batch without touching the records', async () => {
        const stage = makePatternMaskingStage(20, 1024)
        const records = [
            makeRecord(null),
            makeRecord('plain 5'),
            makeRecord('{"message":"hi"}'),
            makeRecord('a long body over the input cap 123'),
        ]
        const bodiesBefore = records.map((r) => r.body)

        await stage.run(records)

        expect(records.map((r) => r.body)).toEqual(bodiesBefore)
        expect(await counterValues(logsPatternBodyKindCounter)).toEqual({
            empty: 1,
            plaintext: 2,
            json_object_or_array: 1,
        })
        expect(await counterValues(logsPatternRuleFiredCounter)).toEqual({ num: 1 })
        expect((await logsPatternInputCappedCounter.get()).values[0].value).toEqual(1)
    })

    it('falls back to the default caps when a configured cap is not a positive integer', async () => {
        const stage = makePatternMaskingStage(Number.NaN, -1)
        await stage.run([makeRecord('x'.repeat(DEFAULT_PATTERN_MAX_INPUT_CHARS + 1))])
        expect((await logsPatternInputCappedCounter.get()).values[0].value).toEqual(1)
    })

    it('keeps the batch when masking throws, so a measurement fault cannot DLQ customer logs', async () => {
        const stage = makePatternMaskingStage(1024, 1024)
        const record = makeRecord(null)
        Object.defineProperty(record, 'body', {
            get: () => {
                throw new Error('boom')
            },
        })

        await stage.run([record])

        expect((await logsPatternStageErrorCounter.get()).values[0].value).toEqual(1)
    })
})
