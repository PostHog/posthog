/**
 * # Chapter 16: TopHog Step Metrics
 *
 * TopHog is an in-process metric extension for pipeline steps. It tracks the
 * top contributors to a named metric across arbitrary dimensions (e.g.
 * `team_id`), keeping only the top N per metric and periodically flushing them
 * to Kafka. It is a troubleshooting tool for multi-tenant systems - "which
 * teams are producing the most events right now?" - not a product-analytics
 * system.
 *
 * This chapter is an introduction; the full reference (metric types, keys,
 * tuning, architecture) lives in `framework/tophog/README.md`.
 *
 * ## Key concepts
 *
 * - **`createTopHogWrapper(registry)`** returns a `topHog(step, factories)`
 *   wrapper. Wrapping a step with metric factories records metrics around each
 *   invocation without changing the step's result or context.
 * - **Metric factories** come in families - `count`, `sum`, `max`, `average`,
 *   and `timer` - each with three timing variants:
 *   - plain (`count`, `sum`, ...): records from the step *input*, before it runs
 *   - `*Result` (`countResult`, ...): records after the step, on *every* result
 *     (ok, drop, dlq, redirect)
 *   - `*Ok` (`countOk`, ...): records after the step, only on OK results
 * - **`MetricTracker` / `TopHog`** is the registry. It accumulates records
 *   keyed by dimension, evicts to stay within `maxKeys`, and on `flush()` emits
 *   the top N entries per metric.
 *
 * ## How it works
 *
 * ```
 * const topHog = createTopHogWrapper(registry)
 * builder.pipe(topHog(myStep, [count('events', (in) => ({ team_id: ... }))]))
 * ```
 */
import { TOPHOG_OUTPUT, TophogOutput } from '~/common/outputs'
import { parseJSON } from '~/common/utils/json-parse'
import { newPipelineBuilder } from '~/ingestion/framework/builders'
import {
    TopHogRegistry,
    count,
    countOk,
    countResult,
    createTopHogWrapper,
    timer,
} from '~/ingestion/framework/extensions/tophog'
import { createOkContext } from '~/ingestion/framework/helpers'
import { dlq, ok } from '~/ingestion/framework/results'
import { TopHog } from '~/ingestion/framework/tophog'
import { createMockIngestionOutputs } from '~/tests/helpers/mock-ingestion-outputs'

interface Event {
    teamId: number
}

// A minimal registry that captures every recorded metric, so a test can assert
// exactly what was recorded without a full TopHog flush.
function createRecordingRegistry(): {
    registry: TopHogRegistry
    records: { metric: string; key: Record<string, string>; value: number }[]
} {
    const records: { metric: string; key: Record<string, string>; value: number }[] = []
    const recorder = (metric: string) => ({
        record: (key: Record<string, string>, value: number) => records.push({ metric, key, value }),
    })
    return {
        records,
        registry: {
            registerSum: (name) => recorder(name),
            registerMax: (name) => recorder(name),
            registerAverage: (name) => recorder(name),
        },
    }
}

describe('TopHog Step Metrics', () => {
    /**
     * Wrapping a step with `count` records once per invocation, keyed by the
     * dimension the factory extracts from the input. The step's own result is
     * untouched.
     */
    it('count records once per invocation, keyed by a dimension', async () => {
        const { registry, records } = createRecordingRegistry()
        const topHog = createTopHogWrapper(registry)

        function processEvent(event: Event) {
            return Promise.resolve(ok({ ...event, processed: true }))
        }

        const pipeline = newPipelineBuilder<Event>()
            .pipe(topHog(processEvent, [count('events', (event) => ({ team_id: String(event.teamId) }))]))
            .build()

        await pipeline.process(createOkContext({ teamId: 1 }, {}))
        await pipeline.process(createOkContext({ teamId: 1 }, {}))
        await pipeline.process(createOkContext({ teamId: 2 }, {}))

        expect(records).toEqual([
            { metric: 'events', key: { team_id: '1' }, value: 1 },
            { metric: 'events', key: { team_id: '1' }, value: 1 },
            { metric: 'events', key: { team_id: '2' }, value: 1 },
        ])
    })

    /**
     * The timing variant distinguishes what counts. `countResult` records for
     * every result; `countOk` records only when the step returns OK. Here the
     * step DLQs its input, so only `countResult` fires.
     */
    it('countResult records on all results, countOk only on OK results', async () => {
        const { registry, records } = createRecordingRegistry()
        const topHog = createTopHogWrapper(registry)

        function rejectEvent(_event: Event) {
            return Promise.resolve(dlq<Event>('invalid'))
        }

        const pipeline = newPipelineBuilder<Event>()
            .pipe(
                topHog(rejectEvent, [
                    countResult('seen', (_result, event) => ({ team_id: String(event.teamId) })),
                    countOk('accepted', (_output, event) => ({ team_id: String(event.teamId) })),
                ])
            )
            .build()

        await pipeline.process(createOkContext({ teamId: 7 }, {}))

        // Only countResult recorded; countOk skipped the non-OK result
        expect(records).toEqual([{ metric: 'seen', key: { team_id: '7' }, value: 1 }])
    })

    /**
     * `timer` records the elapsed wall-clock time of the step in milliseconds,
     * keyed from the input. It records regardless of the result type.
     */
    it('timer records elapsed step time', async () => {
        const { registry, records } = createRecordingRegistry()
        const topHog = createTopHogWrapper(registry)

        async function slowStep(event: Event) {
            await new Promise((resolve) => setTimeout(resolve, 5))
            return ok(event)
        }

        const pipeline = newPipelineBuilder<Event>()
            .pipe(topHog(slowStep, [timer('step_time', (event) => ({ team_id: String(event.teamId) }))]))
            .build()

        await pipeline.process(createOkContext({ teamId: 3 }, {}))

        expect(records).toHaveLength(1)
        expect(records[0].metric).toBe('step_time')
        expect(records[0].key).toEqual({ team_id: '3' })
        expect(typeof records[0].value).toBe('number')
    })

    /**
     * A real `TopHog` registry accumulates records via its `MetricTracker`s and,
     * on `flush()`, emits the top contributors per metric to its Kafka output.
     * Team 1 (3 events) outranks team 2 (1 event).
     */
    it('TopHog aggregates records and flushes top contributors', async () => {
        const outputs = createMockIngestionOutputs<TophogOutput>()
        const tophog = new TopHog({ outputs, pipeline: 'docs', lane: 'test' })
        const topHog = createTopHogWrapper(tophog)

        function processEvent(event: Event) {
            return Promise.resolve(ok(event))
        }

        const pipeline = newPipelineBuilder<Event>()
            .pipe(topHog(processEvent, [count('events_by_team', (event) => ({ team_id: String(event.teamId) }))]))
            .build()

        for (const teamId of [1, 1, 1, 2]) {
            await pipeline.process(createOkContext({ teamId }, {}))
        }

        await tophog.flush()

        // flush() queues one message per top-N entry to the TopHog output
        expect(outputs.queueMessages).toHaveBeenCalledTimes(1)
        const [output, messages] = outputs.queueMessages.mock.calls[0]
        expect(output).toBe(TOPHOG_OUTPUT)

        const entries = (messages as { value: Buffer }[]).map((m) => parseJSON(m.value.toString()))
        const byTeam = new Map(entries.map((e) => [e.key.team_id, e]))

        expect(byTeam.get('1')).toMatchObject({ metric: 'events_by_team', value: 3, count: 3 })
        expect(byTeam.get('2')).toMatchObject({ metric: 'events_by_team', value: 1, count: 1 })
    })
})
