import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { OverflowOutput } from '~/common/outputs'
import { PipelineResult, PipelineResultType, dlq, drop, isOkResult, ok, redirect } from '~/ingestion/framework/results'
import { ParsedMessageData } from '~/ingestion/pipelines/sessionreplay/kafka/types'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

import { KafkaOffsetManager } from './kafka/offset-manager'
import { createPostProcessStep } from './session-batch-post-process-step'
import { SessionReplayPipelineOutput } from './session-replay-pipeline'

describe('createPostProcessStep', () => {
    let mockOffsetManager: jest.Mocked<Pick<KafkaOffsetManager, 'trackOffset'>>

    const makeMessage = (partition: number, offset: number): Message => ({
        topic: 'test-topic',
        partition,
        offset,
        size: 0,
        key: Buffer.from(`key${offset}`),
        value: Buffer.from(`value${offset}`),
        timestamp: 1234567890,
    })

    const team: TeamForReplay = {
        teamId: 1,
        consoleLogIngestionEnabled: false,
        aiTrainingOptedIn: true,
        firstPartyHosts: [],
    }

    const parsedMessage: ParsedMessageData = {
        metadata: { partition: 0, topic: 'test-topic', offset: 1, timestamp: 1234567890, rawSize: 100 },
        distinct_id: 'user-123',
        session_id: 'session-456',
        token: 'test-token',
        eventsByWindowId: { window1: [] },
        eventsRange: { start: DateTime.fromMillis(0), end: DateTime.fromMillis(0) },
        snapshot_source: null,
        snapshot_library: null,
    }

    const recorded: SessionReplayPipelineOutput = { team, parsedMessage }

    const element = (
        result: PipelineResult<SessionReplayPipelineOutput, OverflowOutput>,
        messageId: number,
        message: Message,
        sideEffects: Promise<unknown>[] = []
    ) => ({
        result,
        context: { message, messageId, sideEffects, warnings: [] },
    })

    const createStep = () => createPostProcessStep(mockOffsetManager as unknown as KafkaOffsetManager)

    beforeEach(() => {
        mockOffsetManager = { trackOffset: jest.fn() }
    })

    it('emits one element per result, trimming OK results and passing non-OK results through', async () => {
        const dropped = drop<SessionReplayPipelineOutput>('blocked session')
        const dlqd = dlq<SessionReplayPipelineOutput>('invalid headers', new Error('boom'))
        const redirected = redirect<SessionReplayPipelineOutput, OverflowOutput>('over capacity', 'overflow')
        const input = {
            elements: [
                element(ok(recorded), 10, makeMessage(1, 100)),
                element(dropped, 11, makeMessage(1, 101)),
                element(dlqd, 12, makeMessage(2, 200)),
                element(redirected, 13, makeMessage(2, 201)),
            ],
            batchContext: {},
            batchId: 0,
        }

        const result = await createStep()(input)

        expect(isOkResult(result)).toBe(true)
        if (!isOkResult(result)) {
            return
        }
        const elements = result.value.elements
        expect(elements.map((e) => e.result.type)).toEqual([
            PipelineResultType.OK,
            PipelineResultType.DROP,
            PipelineResultType.DLQ,
            PipelineResultType.REDIRECT,
        ])
        // Non-OK results pass through untouched; the OK result is trimmed to the lightweight row.
        expect(elements[1].result).toBe(dropped)
        expect(elements[2].result).toBe(dlqd)
        expect(elements[3].result).toBe(redirected)
        expect(isOkResult(elements[0].result) ? elements[0].result.value : null).toEqual({
            partition: 1,
            timestamp: expect.any(Number),
        })
        // Each emitted context keeps just the source messageId.
        expect(elements.map((e) => e.context.messageId)).toEqual([10, 11, 12, 13])
    })

    it('tracks the offset of every fed message, non-OK results included', async () => {
        const input = {
            elements: [
                element(ok(recorded), 0, makeMessage(1, 100)),
                element(drop<SessionReplayPipelineOutput>('blocked'), 1, makeMessage(1, 101)),
                element(dlq<SessionReplayPipelineOutput>('invalid', new Error('boom')), 2, makeMessage(2, 200)),
            ],
            batchContext: {},
            batchId: 0,
        }

        await createStep()(input)

        expect(mockOffsetManager.trackOffset.mock.calls.map(([offset]) => offset)).toEqual([
            { partition: 1, offset: 100 },
            { partition: 1, offset: 101 },
            { partition: 2, offset: 200 },
        ])
    })

    it('surfaces the elements side effects on the step result so they can be made durable before commit', async () => {
        const produce1 = Promise.resolve('dlq produce')
        const produce2 = Promise.resolve('overflow produce')
        const input = {
            elements: [
                element(dlq<SessionReplayPipelineOutput>('invalid', new Error('boom')), 0, makeMessage(1, 100), [
                    produce1,
                ]),
                element(
                    redirect<SessionReplayPipelineOutput, OverflowOutput>('over capacity', 'overflow'),
                    1,
                    makeMessage(1, 101),
                    [produce2]
                ),
            ],
            batchContext: {},
            batchId: 0,
        }

        const result = await createStep()(input)

        expect(result.sideEffects).toEqual([produce1, produce2])
    })
})
