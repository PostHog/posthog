import { MetricValueWithName, register } from 'prom-client'

import { IngestionOutput } from '~/common/outputs/ingestion-output'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { IngestionOutputMessage } from '~/common/outputs/types'
import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'

import {
    CDP_INTAKE_MSK_TRANSACTIONAL_EMAIL_OUTPUT,
    CDP_INTAKE_MSK_WORKFLOW_WEBHOOK_OUTPUT,
    CDP_INTAKE_TRANSACTIONAL_EMAIL_OUTPUT,
    CDP_INTAKE_WORKFLOW_WEBHOOK_OUTPUT,
} from '../outputs/outputs'
import { CyclotronJobInvocationHogFlow } from '../types'
import {
    INTAKE_ACK_DEADLINE_MS,
    IntakeOutput,
    IntakeProducer,
    IntakeRun,
    PublishSettlement,
    intakeClusterOf,
    intakeModeOf,
    publishesSettled,
} from './intake-producer'

describe('IntakeProducer', () => {
    let produced: { output: string; message: IngestionOutputMessage }[]
    let produce: (output: string, message: IngestionOutputMessage) => Promise<void>

    const outputs = (): IngestionOutputs<IntakeOutput> => {
        const recorder = (output: string): IngestionOutput => ({
            produce: (message) => produce(output, message),
            queueMessages: () => Promise.resolve(),
            checkHealth: () => Promise.resolve(),
            checkTopicExists: () => Promise.resolve(),
        })
        return new IngestionOutputs({
            [CDP_INTAKE_TRANSACTIONAL_EMAIL_OUTPUT]: recorder(CDP_INTAKE_TRANSACTIONAL_EMAIL_OUTPUT),
            [CDP_INTAKE_WORKFLOW_WEBHOOK_OUTPUT]: recorder(CDP_INTAKE_WORKFLOW_WEBHOOK_OUTPUT),
            [CDP_INTAKE_MSK_TRANSACTIONAL_EMAIL_OUTPUT]: recorder(CDP_INTAKE_MSK_TRANSACTIONAL_EMAIL_OUTPUT),
            [CDP_INTAKE_MSK_WORKFLOW_WEBHOOK_OUTPUT]: recorder(CDP_INTAKE_MSK_WORKFLOW_WEBHOOK_OUTPUT),
        })
    }

    const invocation = (state: Record<string, unknown> = {}): CyclotronJobInvocationHogFlow =>
        ({
            id: new UUIDT().toString(),
            teamId: 7,
            functionId: '0193a7b2-0000-7000-8000-000000000001',
            queue: 'email',
            queuePriority: 0,
            state: { event: { event: '$transactional_email' }, actionStepCount: 0, ...state },
        }) as unknown as CyclotronJobInvocationHogFlow

    beforeEach(() => {
        produced = []
        produce = (output, message) => {
            produced.push({ output, message })
            return Promise.resolve()
        }
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it.each([
        ['transactional-email', CDP_INTAKE_TRANSACTIONAL_EMAIL_OUTPUT, 'fingerprint-a'],
        ['workflow-webhook', CDP_INTAKE_WORKFLOW_WEBHOOK_OUTPUT, undefined],
    ] as const)('produces a %s run to its topic, keyed by its run id', async (kind, output, fingerprint) => {
        const run = invocation({ acceptedAt: '2026-11-12T10:00:00.000Z' })

        const outcome = await new IntakeProducer(outputs()).produce({ kind, invocation: run, fingerprint }, 'shadow')

        expect(outcome).toBe('acked')
        expect(produced).toEqual([
            {
                output,
                message: expect.objectContaining({
                    key: run.id,
                    headers: expect.objectContaining({ run_id: run.id, run_kind: kind, team_id: '7' }),
                }),
            },
        ])
        const value = parseJSON(produced[0].message.value!.toString())
        expect(value).toMatchObject({ v: 1, kind, teamId: 7, job: { id: run.id, queueName: 'email' } })
        expect(value.fingerprint).toEqual(fingerprint)
        expect(value.job.state.state.acceptedAt).toBe('2026-11-12T10:00:00.000Z')
    })

    it.each([
        ['b-1:9094', '7', 'shadow', 'transactional-email', CDP_INTAKE_MSK_TRANSACTIONAL_EMAIL_OUTPUT, 'msk'],
        ['b-1:9094', '*', 'async', 'workflow-webhook', CDP_INTAKE_MSK_WORKFLOW_WEBHOOK_OUTPUT, 'msk'],
        ['b-1:9094', '8', 'shadow', 'transactional-email', CDP_INTAKE_TRANSACTIONAL_EMAIL_OUTPUT, 'warpstream'],
        ['', '*', 'async', 'workflow-webhook', CDP_INTAKE_WORKFLOW_WEBHOOK_OUTPUT, 'warpstream'],
    ] as const)(
        'with MSK brokers %p and MSK teams %p, routes a %s %s run of team 7 to %s',
        async (brokers, mskTeams, mode, kind, output, cluster) => {
            const clusterOf = intakeClusterOf({
                KAFKA_MSK_CDP_INTAKE_PRODUCER_METADATA_BROKER_LIST: brokers,
                CDP_INTAKE_MSK_TEAMS: mskTeams,
            })
            const acked = async (): Promise<number> => {
                const metric = await register.getSingleMetric('cdp_intake_launches_total')!.get()
                return metric.values
                    .filter(
                        (v) =>
                            v.labels.kind === kind &&
                            v.labels.mode === mode &&
                            v.labels.outcome === 'acked' &&
                            v.labels.cluster === cluster
                    )
                    .reduce((sum, v) => sum + v.value, 0)
            }
            const before = await acked()

            await new IntakeProducer(outputs(), undefined, undefined, clusterOf).produce(
                { kind, invocation: invocation() },
                mode
            )

            expect(produced.map((p) => p.output)).toEqual([output])
            expect((await acked()) - before).toBe(1)
        }
    )

    it('produces nothing for a run too large for the topic', async () => {
        const run = invocation({ variables: { body: 'x'.repeat(2 * 1024 * 1024) } })

        const outcome = await new IntakeProducer(outputs()).produce(
            { kind: 'transactional-email', invocation: run },
            'shadow'
        )

        expect(outcome).toBe('too_large')
        expect(produced).toEqual([])
    })

    it.each([
        ['the broker refuses it', () => Promise.reject(new Error('Broker: Not enough in-sync replicas'))],
        ['no ack arrives before the deadline', () => new Promise<void>(() => {})],
    ])('reports a produce as unacked when %s', async (_case, failingProduce) => {
        jest.useFakeTimers()
        produce = failingProduce

        const outcome = new IntakeProducer(outputs()).produce(
            { kind: 'workflow-webhook', invocation: invocation() },
            'shadow'
        )
        await jest.advanceTimersByTimeAsync(INTAKE_ACK_DEADLINE_MS)

        await expect(outcome).resolves.toBe('unacked')
    })

    it.each([
        ['the first is refused, then the second acked', 0, 1],
        ['the second is acked, then the first refused', 1, 0],
    ])('settles only once every publish past its ack deadline is settled: %s', async (_, first, second) => {
        jest.useFakeTimers()
        const held: { ack: () => void; refuse: (error: Error) => void }[] = []
        produce = () => new Promise<void>((ack, refuse) => held.push({ ack, refuse }))
        const settlement = new PublishSettlement()
        let drained: 'pending' | 'fulfilled' | 'rejected' = 'pending'
        const producer = new IntakeProducer(outputs())

        const outcomes = [
            producer.produce({ kind: 'transactional-email', invocation: invocation() }, 'async', settlement),
            producer.produce({ kind: 'transactional-email', invocation: invocation() }, 'async', settlement),
        ]
        await jest.advanceTimersByTimeAsync(INTAKE_ACK_DEADLINE_MS)
        await expect(Promise.all(outcomes)).resolves.toEqual(['unacked', 'unacked'])
        publishesSettled(settlement).then(
            () => (drained = 'fulfilled'),
            () => (drained = 'rejected')
        )
        const settle = (index: number): void =>
            index === 0 ? held[0].refuse(new Error('Broker: Not enough in-sync replicas')) : held[1].ack()
        settle(first)
        await jest.advanceTimersByTimeAsync(0)
        expect(drained).toBe('pending')

        settle(second)
        await jest.advanceTimersByTimeAsync(0)

        expect(drained).toBe('fulfilled')
    })

    it("settles each handle on its own publishes, without waiting on another handle's", async () => {
        jest.useFakeTimers()
        const held: (() => void)[] = []
        produce = () => new Promise<void>((ack) => held.push(ack))
        const producer = new IntakeProducer(outputs())
        const [first, second] = [new PublishSettlement(), new PublishSettlement()]
        const settled = [false, false]

        void producer.produce({ kind: 'transactional-email', invocation: invocation() }, 'async', first)
        void producer.produce({ kind: 'transactional-email', invocation: invocation() }, 'async', second)
        await jest.advanceTimersByTimeAsync(INTAKE_ACK_DEADLINE_MS)
        ;[first, second].forEach((settlement, i) => void publishesSettled(settlement).then(() => (settled[i] = true)))
        await jest.advanceTimersByTimeAsync(0)
        expect(settled).toEqual([false, false])

        held[1]()
        await jest.advanceTimersByTimeAsync(0)
        expect(settled).toEqual([false, true])

        held[0]()
        await jest.advanceTimersByTimeAsync(0)
        expect(settled).toEqual([true, true])
    })

    const everyTrapThrows: ProxyHandler<PublishSettlement> = {
        get: () => {
            throw new Error('trap')
        },
        has: () => {
            throw new Error('trap')
        },
        getPrototypeOf: () => {
            throw new Error('trap')
        },
        ownKeys: () => {
            throw new Error('trap')
        },
    }
    const settlementKinds: [string, () => PublishSettlement][] = [
        ['a settlement', () => new PublishSettlement()],
        ['a proxy whose every trap throws', () => new Proxy(new PublishSettlement(), everyTrapThrows)],
    ]

    it.each(settlementKinds)('answers acked from the broker when the produce carries %s', async (_, makeSettlement) => {
        const settlement = makeSettlement()

        const outcome = await new IntakeProducer(outputs()).produce(
            { kind: 'transactional-email', invocation: invocation() },
            'async',
            settlement
        )

        expect(outcome).toBe('acked')
        await expect(publishesSettled(settlement)).resolves.toBeUndefined()
    })

    it('holds a proxy whose every trap throws open past the ack deadline until the broker answers', async () => {
        jest.useFakeTimers()
        let ack!: () => void
        produce = () => new Promise<void>((resolve) => (ack = resolve))
        const settlement = new Proxy(new PublishSettlement(), everyTrapThrows)
        let drained = false

        const outcome = new IntakeProducer(outputs()).produce(
            { kind: 'transactional-email', invocation: invocation() },
            'async',
            settlement
        )
        await jest.advanceTimersByTimeAsync(INTAKE_ACK_DEADLINE_MS)
        await expect(outcome).resolves.toBe('unacked')
        void publishesSettled(settlement).then(() => (drained = true))
        await jest.advanceTimersByTimeAsync(0)
        expect(drained).toBe(false)

        ack()
        await jest.advanceTimersByTimeAsync(0)

        expect(drained).toBe(true)
    })

    it('records the wait for the ack in milliseconds', async () => {
        jest.useFakeTimers()
        produce = () => new Promise<void>((resolve) => setTimeout(resolve, 400))
        const ackSum = async (): Promise<number> => {
            const metric = await register.getSingleMetric('cdp_intake_ack_ms')!.get()
            const values = metric.values as MetricValueWithName<string>[]
            const sum = values.find(
                (value) => value.metricName === 'cdp_intake_ack_ms_sum' && value.labels.kind === 'workflow-webhook'
            )
            return sum?.value ?? 0
        }
        const before = await ackSum()

        const outcome = new IntakeProducer(outputs()).produce(
            { kind: 'workflow-webhook', invocation: invocation() },
            'shadow'
        )
        await jest.advanceTimersByTimeAsync(400)

        await expect(outcome).resolves.toBe('acked')
        expect((await ackSum()) - before).toBe(400)
    })

    it.each([
        ['', '', 'off'],
        ['7', '', 'shadow'],
        ['*', '', 'shadow'],
        ['', '7', 'async'],
        ['7', '7', 'async'],
        ['8,9', '10', 'off'],
    ])('runs team 7 with shadow teams %p and async teams %p as %s', (shadow, asyncTeams, mode) => {
        const modeOf = intakeModeOf({ CDP_INTAKE_KAFKA_SHADOW_TEAMS: shadow, CDP_INTAKE_KAFKA_ASYNC_TEAMS: asyncTeams })

        expect(modeOf(7)).toBe(mode)
    })
})

// Compile-only, never called: tsc fails on these directives once an empty object or a spread copy type-checks as the
// settlement `produce` takes.
const _settlementTypeChecks = (producer: IntakeProducer, run: IntakeRun): void => {
    // @ts-expect-error an empty object is not a settlement
    void producer.produce(run, 'async', {})
    // @ts-expect-error a spread copy is not the handle its publishes are tracked on
    void producer.produce(run, 'async', { ...new PublishSettlement() })
}
