import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { OverflowOutput } from '~/common/outputs'
import { PipelineResultWithContext } from '~/ingestion/framework/pipeline.interface'
import { PipelineResult, PipelineResultType, dlq, drop, isOkResult, ok, redirect } from '~/ingestion/framework/results'
import { ParsedMessageData } from '~/ingestion/pipelines/sessionreplay/kafka/types'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

import { KafkaOffsetManager } from './kafka/offset-manager'
import { createReplayAfterRecordHook } from './session-batch-after-record'
import { SessionReplayPipelineOutput } from './session-replay-pipeline'

describe('createReplayAfterRecordHook', () => {
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
        message: Message
    ): PipelineResultWithContext<SessionReplayPipelineOutput, { message: Message }, OverflowOutput> => ({
        result,
        context: { message, sideEffects: [], warnings: [] },
    })

    const createHook = () => createReplayAfterRecordHook(mockOffsetManager as unknown as KafkaOffsetManager)

    beforeEach(() => {
        mockOffsetManager = { trackOffset: jest.fn() }
    })

    it('emits one element per result, trimming OK results and passing non-OK results through', () => {
        const dropped = drop<SessionReplayPipelineOutput>('blocked session')
        const dlqd = dlq<SessionReplayPipelineOutput>('invalid headers', new Error('boom'))
        const redirected = redirect<SessionReplayPipelineOutput, OverflowOutput>('over capacity', 'overflow')

        const elements = createHook()([
            element(ok(recorded), makeMessage(1, 100)),
            element(dropped, makeMessage(1, 101)),
            element(dlqd, makeMessage(2, 200)),
            element(redirected, makeMessage(2, 201)),
        ])

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
        // The heavy Kafka message is dropped from every context.
        expect(elements.every((e) => !('message' in e.context))).toBe(true)
    })

    it('tracks the offset of every message, non-OK results included', () => {
        createHook()([
            element(ok(recorded), makeMessage(1, 100)),
            element(drop<SessionReplayPipelineOutput>('blocked'), makeMessage(1, 101)),
            element(dlq<SessionReplayPipelineOutput>('invalid', new Error('boom')), makeMessage(2, 200)),
        ])

        expect(mockOffsetManager.trackOffset.mock.calls.map(([offset]) => offset)).toEqual([
            { partition: 1, offset: 100 },
            { partition: 1, offset: 101 },
            { partition: 2, offset: 200 },
        ])
    })
})
