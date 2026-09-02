import type { Counter } from 'prom-client'

import { PATTERN_CAPS, PATTERN_VERSION } from './log-pattern-mask'
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

    it('tallies body kinds, rule fires, and input caps across a batch without touching the body', async () => {
        const stage = makePatternMaskingStage(['message'])
        const records = [
            makeRecord(null),
            makeRecord('plain 5'),
            makeRecord('{"message":"hi"}'),
            makeRecord('x'.repeat(PATTERN_CAPS.maxInputChars + 1)),
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

    it.each([
        [
            'the masked body, not the raw one',
            'request 0f2d6faf-07e3-4cff-bf47-7efa1024aee2 took 7141ms',
            'request <UUID> took <N>ms',
        ],
        ['a plain body', 'retry 5', 'retry <N>'],
        ['an empty body, which must still carry a version or it reads as written before masking', null, ''],
    ])('stamps pattern and version onto the record: %s', async (_name, body, expected) => {
        const stage = makePatternMaskingStage(['message'])
        const record = makeRecord(body)

        await stage.run([record])

        expect(record).toMatchObject({ pattern: expected, pattern_version: PATTERN_VERSION })
    })

    it('keeps the batch when masking throws, so a measurement fault cannot DLQ customer logs', async () => {
        const stage = makePatternMaskingStage(['message'])
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
