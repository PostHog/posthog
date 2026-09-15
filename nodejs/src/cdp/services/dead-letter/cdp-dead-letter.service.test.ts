import { Message } from 'node-rdkafka'

import { CdpOutputs } from '../../cdp-services'
import { CDP_EVENTS_DLQ_OUTPUT } from '../../outputs/outputs'
import { DeadLetterFailure, HogFunctionInvocationGlobals } from '../../types'
import { CdpDeadLetterService } from './cdp-dead-letter.service'

describe('CdpDeadLetterService', () => {
    let produce: jest.Mock
    let outputs: CdpOutputs
    let messagesByGlobals: Map<HogFunctionInvocationGlobals, Message>

    const message = (uuid: string, offset = 10): Message =>
        ({
            value: Buffer.from(JSON.stringify({ uuid })),
            key: Buffer.from(uuid),
            topic: 'clickhouse_events_json',
            partition: 3,
            offset,
            size: 0,
            headers: [{ token: Buffer.from('phc_abc') }],
        }) as unknown as Message

    const globalsFor = (teamId: number, uuid: string): HogFunctionInvocationGlobals =>
        ({ project: { id: teamId }, event: { uuid } }) as HogFunctionInvocationGlobals

    const defaultGlobals = globalsFor(2, 'event-1')

    const failure = (overrides: Partial<DeadLetterFailure> = {}): DeadLetterFailure => ({
        globals: defaultGlobals,
        sourceId: 'fn-1',
        sourceKind: 'hog_function',
        step: 'inputs',
        error: 'Invalid arguments',
        ...overrides,
    })

    const createService = (enabled = true): CdpDeadLetterService =>
        new CdpDeadLetterService(
            { CDP_DLQ_ENABLED: enabled, CDP_DLQ_BATCH_FAIL_RATIO: 0.1 },
            {
                outputs,
                output: CDP_EVENTS_DLQ_OUTPUT,
                consumerGroup: 'cdp-processed-events-consumer',
                resolveMessage: (globals) => messagesByGlobals.get(globals),
            }
        )

    beforeEach(() => {
        produce = jest.fn().mockResolvedValue(undefined)
        outputs = { produce } as unknown as CdpOutputs
        messagesByGlobals = new Map()
        messagesByGlobals.set(defaultGlobals, message('event-1'))
    })

    it('parks the original bytes with the source position and the failed function', async () => {
        const service = createService()
        service.recordBuildFailures([failure()])

        await service.produceForBatch([message('event-1')])

        expect(produce).toHaveBeenCalledTimes(1)
        expect(produce).toHaveBeenCalledWith(CDP_EVENTS_DLQ_OUTPUT, {
            value: Buffer.from(JSON.stringify({ uuid: 'event-1' })),
            key: Buffer.from('event-1'),
            headers: {
                token: 'phc_abc',
                dlq_step: 'inputs',
                dlq_reason: 'Invalid arguments',
                dlq_timestamp: expect.any(String),
                dlq_topic: 'clickhouse_events_json',
                dlq_partition: '3',
                dlq_offset: '10',
                dlq_consumer_group: 'cdp-processed-events-consumer',
                dlq_team_id: '2',
                dlq_hog_function_ids: 'fn-1',
                dlq_hog_flow_ids: '',
            },
        })
    })

    it('writes one record per event and step, naming every source that failed at that step', async () => {
        const service = createService()
        service.recordBuildFailures([
            failure({ sourceId: 'fn-1' }),
            failure({ sourceId: 'fn-2' }),
            failure({ sourceId: 'flow-1', sourceKind: 'hog_flow' }),
            failure({ sourceId: 'fn-3', step: 'filter' }),
        ])

        await service.produceForBatch([message('event-1')])

        expect(produce).toHaveBeenCalledTimes(2)
        const byStep = Object.fromEntries(produce.mock.calls.map(([, m]) => [m.headers.dlq_step, m.headers]))
        expect(byStep.inputs).toMatchObject({ dlq_hog_function_ids: 'fn-1,fn-2', dlq_hog_flow_ids: 'flow-1' })
        expect(byStep.filter).toMatchObject({ dlq_hog_function_ids: 'fn-3', dlq_hog_flow_ids: '' })
    })

    it('parks a message that could not be parsed, naming no function', async () => {
        const service = createService()
        service.recordMessageFailure(message('event-1'), {
            step: 'parse',
            error: 'Unexpected end of JSON input',
        })

        await service.produceForBatch([])

        expect(produce).toHaveBeenCalledTimes(1)
        expect(produce.mock.calls[0][1].headers).toMatchObject({
            dlq_step: 'parse',
            dlq_reason: 'Unexpected end of JSON input',
            // No team and no functions: a replay rebuilds everything the team has, because nothing
            // was built the first time.
            dlq_team_id: '',
            dlq_hog_function_ids: '',
            dlq_hog_flow_ids: '',
        })
    })

    it('parks an event that threw outside the handled failures', async () => {
        const service = createService()
        service.recordProcessFailure(defaultGlobals, new Error('Cannot read properties of undefined'))

        await service.produceForBatch([message('event-1')])

        expect(produce.mock.calls[0][1].headers).toMatchObject({
            dlq_step: 'process',
            dlq_team_id: '2',
            dlq_hog_function_ids: '',
        })
    })

    it('fails the batch instead of parking it when most of it throws unexpectedly', async () => {
        const service = createService()
        const messages = [10, 11, 12, 13].map((offset) => message(`event-${offset}`, offset))
        for (const [index, uuid] of ['event-10', 'event-11', 'event-12'].entries()) {
            const globals = globalsFor(2, uuid)
            messagesByGlobals.set(globals, messages[index])
            service.recordProcessFailure(globals, new Error('boom'))
        }

        await expect(service.produceForBatch(messages)).rejects.toThrow('Refusing to dead-letter 3 of 4')
        expect(produce).not.toHaveBeenCalled()
    })

    it('parks a lone unexpected failure rather than breaking on a small batch', async () => {
        // A ratio says nothing about one message. Breaking here would stall the partition on the
        // very event this path exists to park.
        const service = createService()
        service.recordProcessFailure(defaultGlobals, new Error('boom'))

        await service.produceForBatch([message('event-1')])

        expect(produce).toHaveBeenCalledTimes(1)
    })

    it('still parks a whole batch of filter and input failures', async () => {
        // One broken builtin legitimately breaks every function in a batch. Those records are
        // exactly what the replay needs, so the ratio must not apply to them.
        const service = createService()
        const second = globalsFor(2, 'event-2')
        const messages = [message('event-1', 10), message('event-2', 11)]
        messagesByGlobals.set(second, messages[1])
        service.recordBuildFailures([failure(), failure({ globals: second })])

        await service.produceForBatch(messages)

        expect(produce).toHaveBeenCalledTimes(2)
    })

    it('gives each team its own record when two events collide on the same client-supplied ID', async () => {
        // Event IDs come from the client, so two teams can send the same one on a topic that
        // carries every team. Nothing here keys on the ID, so there is nothing to collide.
        const service = createService()
        const teamA = globalsFor(2, 'shared')
        const teamB = globalsFor(3, 'shared')
        const messageA = message('a', 10)
        const messageB = message('b', 11)
        messagesByGlobals.set(teamA, messageA)
        messagesByGlobals.set(teamB, messageB)

        service.recordBuildFailures([
            failure({ globals: teamA, sourceId: 'fn-a' }),
            failure({ globals: teamB, sourceId: 'fn-b' }),
        ])
        await service.produceForBatch([messageA, messageB])

        expect(produce).toHaveBeenCalledTimes(2)
        const byTeam = Object.fromEntries(produce.mock.calls.map(([, m]) => [m.headers.dlq_team_id, m]))
        expect(byTeam['2'].value).toEqual(messageA.value)
        expect(byTeam['2'].headers.dlq_hog_function_ids).toBe('fn-a')
        expect(byTeam['3'].value).toEqual(messageB.value)
        expect(byTeam['3'].headers.dlq_hog_function_ids).toBe('fn-b')
    })

    it('produces nothing while the queue is disabled', async () => {
        const service = createService(false)
        service.recordBuildFailures([failure()])

        await service.produceForBatch([message('event-1')])

        expect(produce).not.toHaveBeenCalled()
    })

    it('fails the batch when a record cannot be produced', async () => {
        produce.mockRejectedValue(new Error('broker unavailable'))
        const service = createService()
        service.recordBuildFailures([failure()])

        await expect(service.produceForBatch([message('event-1')])).rejects.toThrow('broker unavailable')
    })

    it('clears recorded failures so the next batch does not repark them', async () => {
        const service = createService()
        service.recordBuildFailures([failure()])
        await service.produceForBatch([message('event-1')])

        await service.produceForBatch([message('event-1')])

        expect(produce).toHaveBeenCalledTimes(1)
    })
})
