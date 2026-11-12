import { IngestionOutput } from '~/common/outputs/ingestion-output'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { IngestionOutputMessage } from '~/common/outputs/types'
import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'

import { CDP_INTAKE_TRANSACTIONAL_EMAIL_OUTPUT, CDP_INTAKE_WORKFLOW_WEBHOOK_OUTPUT } from '../outputs/outputs'
import { CyclotronJobInvocationHogFlow } from '../types'
import { INTAKE_ACK_DEADLINE_MS, IntakeOutput, IntakeProducer, intakeModeOf } from './intake-producer'

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
