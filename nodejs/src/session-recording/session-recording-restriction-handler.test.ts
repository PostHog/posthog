import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '../kafka/producer'
import { EventIngestionRestrictionManager, Restriction } from '../utils/event-ingestion-restriction-manager'
import { PromiseScheduler } from '../utils/promise-scheduler'
import { SessionRecordingIngesterMetrics } from './metrics'
import { SessionRecordingRestrictionHandler } from './session-recording-restriction-handler'

function createMessage(overrides: Partial<Message> = {}): Message {
    return {
        value: Buffer.from('test'),
        headers: new Set(),
        partition: 0,
        offset: 100,
        key: null,
        size: 4,
        topic: 'test-topic',
        ...overrides,
    } as Message
}

describe('SessionRecordingRestrictionHandler', () => {
    let restrictionManager: EventIngestionRestrictionManager
    let overflowProducer: KafkaProducerWrapper
    let promiseScheduler: PromiseScheduler
    let handler: SessionRecordingRestrictionHandler
    const overflowTopic = 'test-overflow-topic'

    beforeEach(() => {
        restrictionManager = {
            getAppliedRestrictions: jest.fn().mockReturnValue(new Set()),
        } as unknown as EventIngestionRestrictionManager

        overflowProducer = {
            produce: jest.fn().mockResolvedValue(undefined),
        } as unknown as KafkaProducerWrapper

        promiseScheduler = {
            schedule: jest.fn().mockResolvedValue(undefined),
        } as unknown as PromiseScheduler

        jest.spyOn(SessionRecordingIngesterMetrics, 'observeDroppedByRestrictions')
        jest.spyOn(SessionRecordingIngesterMetrics, 'observeOverflowedByRestrictions')
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    describe('when not consuming from overflow', () => {
        beforeEach(() => {
            handler = new SessionRecordingRestrictionHandler(
                restrictionManager,
                overflowTopic,
                overflowProducer,
                promiseScheduler,
                false
            )
        })

        it('passes through messages without token', () => {
            const messages: Message[] = [createMessage()]

            const result = handler.applyRestrictions(messages)

            expect(result).toEqual(messages)
            expect(restrictionManager.getAppliedRestrictions).not.toHaveBeenCalled()
            expect(SessionRecordingIngesterMetrics.observeDroppedByRestrictions).not.toHaveBeenCalled()
            expect(SessionRecordingIngesterMetrics.observeOverflowedByRestrictions).not.toHaveBeenCalled()
        })

        it('passes through messages when no restrictions match', () => {
            const messages: Message[] = [
                createMessage({
                    headers: [{ token: 'token-1' }, { distinct_id: 'user-1' }],
                }),
            ]

            const result = handler.applyRestrictions(messages)

            expect(result).toEqual(messages)
            expect(restrictionManager.getAppliedRestrictions).toHaveBeenCalledWith('token-1', {
                token: 'token-1',
                distinct_id: 'user-1',
                session_id: undefined,
                timestamp: undefined,
                event: undefined,
                uuid: undefined,
                force_disable_person_processing: false,
                historical_migration: false,
            })
            expect(SessionRecordingIngesterMetrics.observeDroppedByRestrictions).not.toHaveBeenCalled()
            expect(SessionRecordingIngesterMetrics.observeOverflowedByRestrictions).not.toHaveBeenCalled()
        })

        it('filters out messages that should be dropped', () => {
            const messages: Message[] = [
                createMessage({
                    value: Buffer.from('test1'),
                    headers: [{ token: 'drop-token' }, { distinct_id: 'user-1' }],
                    offset: 100,
                }),
                createMessage({
                    value: Buffer.from('test2'),
                    headers: [{ token: 'keep-token' }, { distinct_id: 'user-2' }],
                    offset: 101,
                }),
            ]

            jest.mocked(restrictionManager.getAppliedRestrictions).mockImplementation((token) =>
                token === 'drop-token' ? new Set([Restriction.DROP_EVENT]) : new Set()
            )

            const result = handler.applyRestrictions(messages)

            expect(result).toHaveLength(1)
            expect(result[0]).toBe(messages[1])
            expect(SessionRecordingIngesterMetrics.observeDroppedByRestrictions).toHaveBeenCalledWith(1)
            expect(SessionRecordingIngesterMetrics.observeOverflowedByRestrictions).not.toHaveBeenCalled()
        })

        it('redirects messages to overflow when forced', () => {
            const messages: Message[] = [
                createMessage({
                    headers: [{ token: 'overflow-token' }, { distinct_id: 'user-1' }],
                }),
            ]

            jest.mocked(restrictionManager.getAppliedRestrictions).mockReturnValue(
                new Set([Restriction.FORCE_OVERFLOW])
            )

            const result = handler.applyRestrictions(messages)

            expect(result).toEqual([])
            expect(SessionRecordingIngesterMetrics.observeOverflowedByRestrictions).toHaveBeenCalledWith(1)
            expect(SessionRecordingIngesterMetrics.observeDroppedByRestrictions).not.toHaveBeenCalled()
            expect(promiseScheduler.schedule).toHaveBeenCalled()
        })

        it('handles mixed messages correctly', () => {
            const messages: Message[] = [
                createMessage({
                    value: Buffer.from('test1'),
                    headers: [{ token: 'drop-token' }, { distinct_id: 'user-1' }],
                    offset: 100,
                }),
                createMessage({
                    value: Buffer.from('test2'),
                    headers: [{ token: 'overflow-token' }, { distinct_id: 'user-2' }],
                    offset: 101,
                }),
                createMessage({
                    value: Buffer.from('test3'),
                    headers: [{ token: 'keep-token' }, { distinct_id: 'user-3' }],
                    offset: 102,
                }),
                createMessage({
                    value: Buffer.from('test4'),
                    headers: [],
                    offset: 103,
                }),
            ]

            jest.mocked(restrictionManager.getAppliedRestrictions).mockImplementation((token) => {
                if (token === 'drop-token') {
                    return new Set([Restriction.DROP_EVENT])
                }
                if (token === 'overflow-token') {
                    return new Set([Restriction.FORCE_OVERFLOW])
                }
                return new Set()
            })

            const result = handler.applyRestrictions(messages)

            expect(result).toHaveLength(2)
            expect(result[0]).toBe(messages[2])
            expect(result[1]).toBe(messages[3])
            expect(SessionRecordingIngesterMetrics.observeDroppedByRestrictions).toHaveBeenCalledWith(1)
            expect(SessionRecordingIngesterMetrics.observeOverflowedByRestrictions).toHaveBeenCalledWith(1)
        })

        it('produces overflow messages with correct topic and headers', async () => {
            const messages: Message[] = [
                createMessage({
                    headers: [{ token: 'overflow-token' }, { distinct_id: 'user-1' }, { timestamp: '2024-01-01' }],
                    key: Buffer.from('key'),
                }),
            ]

            jest.mocked(restrictionManager.getAppliedRestrictions).mockReturnValue(
                new Set([Restriction.FORCE_OVERFLOW])
            )

            handler.applyRestrictions(messages)

            const scheduledPromise = jest.mocked(promiseScheduler.schedule).mock.calls[0][0]
            await scheduledPromise

            expect(overflowProducer.produce).toHaveBeenCalledWith({
                topic: overflowTopic,
                value: messages[0].value,
                key: messages[0].key,
                headers: {
                    token: 'overflow-token',
                    distinct_id: 'user-1',
                    timestamp: '2024-01-01',
                },
            })
        })

        it('preserves message order for filtered messages', () => {
            const messages: Message[] = [
                createMessage({
                    value: Buffer.from('msg1'),
                    headers: [{ token: 'token-1' }, { distinct_id: 'user-1' }],
                    offset: 100,
                }),
                createMessage({
                    value: Buffer.from('msg2'),
                    headers: [{ token: 'token-2' }, { distinct_id: 'user-2' }],
                    offset: 101,
                }),
                createMessage({
                    value: Buffer.from('msg3'),
                    headers: [{ token: 'token-3' }, { distinct_id: 'user-3' }],
                    offset: 102,
                }),
                createMessage({
                    value: Buffer.from('msg4'),
                    headers: [{ token: 'token-4' }, { distinct_id: 'user-4' }],
                    offset: 103,
                }),
            ]

            const result = handler.applyRestrictions(messages)

            expect(result).toHaveLength(4)
            expect(result[0]).toBe(messages[0])
            expect(result[1]).toBe(messages[1])
            expect(result[2]).toBe(messages[2])
            expect(result[3]).toBe(messages[3])
        })

        it('preserves message order when producing to overflow', async () => {
            const messages: Message[] = [
                createMessage({
                    value: Buffer.from('overflow1'),
                    headers: [{ token: 'overflow-1' }, { distinct_id: 'user-1' }],
                    offset: 100,
                    key: Buffer.from('key1'),
                }),
                createMessage({
                    value: Buffer.from('overflow2'),
                    headers: [{ token: 'overflow-2' }, { distinct_id: 'user-2' }],
                    offset: 101,
                    key: Buffer.from('key2'),
                }),
                createMessage({
                    value: Buffer.from('overflow3'),
                    headers: [{ token: 'overflow-3' }, { distinct_id: 'user-3' }],
                    offset: 102,
                    key: Buffer.from('key3'),
                }),
            ]

            jest.mocked(restrictionManager.getAppliedRestrictions).mockReturnValue(
                new Set([Restriction.FORCE_OVERFLOW])
            )

            handler.applyRestrictions(messages)

            const scheduledPromise = jest.mocked(promiseScheduler.schedule).mock.calls[0][0]
            await scheduledPromise

            expect(overflowProducer.produce).toHaveBeenCalledTimes(3)

            const produceCalls = jest.mocked(overflowProducer.produce).mock.calls
            expect(produceCalls[0][0].value).toEqual(Buffer.from('overflow1'))
            expect(produceCalls[0][0].key).toEqual(Buffer.from('key1'))
            expect(produceCalls[1][0].value).toEqual(Buffer.from('overflow2'))
            expect(produceCalls[1][0].key).toEqual(Buffer.from('key2'))
            expect(produceCalls[2][0].value).toEqual(Buffer.from('overflow3'))
            expect(produceCalls[2][0].key).toEqual(Buffer.from('key3'))
        })

        it('passes session_id to restriction manager when present in headers', () => {
            const messages: Message[] = [
                createMessage({
                    headers: [{ token: 'token-1' }, { distinct_id: 'user-1' }, { session_id: 'session-123' }],
                }),
            ]

            const result = handler.applyRestrictions(messages)

            expect(result).toEqual(messages)
            expect(restrictionManager.getAppliedRestrictions).toHaveBeenCalledWith('token-1', {
                token: 'token-1',
                distinct_id: 'user-1',
                session_id: 'session-123',
                timestamp: undefined,
                event: undefined,
                uuid: undefined,
                force_disable_person_processing: false,
                historical_migration: false,
            })
        })

        it('drops messages when session_id matches drop restriction', () => {
            const messages: Message[] = [
                createMessage({
                    value: Buffer.from('test1'),
                    headers: [{ token: 'token-1' }, { distinct_id: 'user-1' }, { session_id: 'drop-session' }],
                    offset: 100,
                }),
                createMessage({
                    value: Buffer.from('test2'),
                    headers: [{ token: 'token-1' }, { distinct_id: 'user-1' }, { session_id: 'keep-session' }],
                    offset: 101,
                }),
            ]

            jest.mocked(restrictionManager.getAppliedRestrictions).mockImplementation((_token, lookup) =>
                lookup?.session_id === 'drop-session' ? new Set([Restriction.DROP_EVENT]) : new Set()
            )

            const result = handler.applyRestrictions(messages)

            expect(result).toHaveLength(1)
            expect(result[0]).toBe(messages[1])
            expect(SessionRecordingIngesterMetrics.observeDroppedByRestrictions).toHaveBeenCalledWith(1)
        })

        it('redirects messages to overflow when session_id matches overflow restriction', () => {
            const messages: Message[] = [
                createMessage({
                    headers: [{ token: 'token-1' }, { distinct_id: 'user-1' }, { session_id: 'overflow-session' }],
                }),
            ]

            jest.mocked(restrictionManager.getAppliedRestrictions).mockImplementation((_token, lookup) =>
                lookup?.session_id === 'overflow-session' ? new Set([Restriction.FORCE_OVERFLOW]) : new Set()
            )

            const result = handler.applyRestrictions(messages)

            expect(result).toEqual([])
            expect(SessionRecordingIngesterMetrics.observeOverflowedByRestrictions).toHaveBeenCalledWith(1)
            expect(promiseScheduler.schedule).toHaveBeenCalled()
        })

        it('handles messages with session_id but no distinct_id', () => {
            const messages: Message[] = [
                createMessage({
                    headers: [{ token: 'token-1' }, { session_id: 'session-123' }],
                }),
            ]

            const result = handler.applyRestrictions(messages)

            expect(result).toEqual(messages)
            expect(restrictionManager.getAppliedRestrictions).toHaveBeenCalledWith('token-1', {
                token: 'token-1',
                distinct_id: undefined,
                session_id: 'session-123',
                timestamp: undefined,
                event: undefined,
                uuid: undefined,
                force_disable_person_processing: false,
                historical_migration: false,
            })
        })

        it('passes event name and uuid to restriction manager when present in headers', () => {
            const messages: Message[] = [
                createMessage({
                    headers: [
                        { token: 'token-1' },
                        { distinct_id: 'user-1' },
                        { session_id: 'session-123' },
                        { event: '$snapshot' },
                        { uuid: 'event-uuid-456' },
                    ],
                }),
            ]

            const result = handler.applyRestrictions(messages)

            expect(result).toEqual(messages)
            expect(restrictionManager.getAppliedRestrictions).toHaveBeenCalledWith('token-1', {
                token: 'token-1',
                distinct_id: 'user-1',
                session_id: 'session-123',
                timestamp: undefined,
                event: '$snapshot',
                uuid: 'event-uuid-456',
                force_disable_person_processing: false,
                historical_migration: false,
            })
        })

        it('throws error when overflow producer is undefined and message should overflow', () => {
            const handlerWithoutProducer = new SessionRecordingRestrictionHandler(
                restrictionManager,
                overflowTopic,
                undefined,
                promiseScheduler,
                false
            )

            const messages: Message[] = [
                createMessage({
                    headers: [{ token: 'overflow-token' }, { distinct_id: 'user-1' }],
                }),
            ]

            jest.mocked(restrictionManager.getAppliedRestrictions).mockReturnValue(
                new Set([Restriction.FORCE_OVERFLOW])
            )

            expect(() => handlerWithoutProducer.applyRestrictions(messages)).toThrow(
                'Cannot redirect 1 messages to overflow: no overflow producer available'
            )
        })
    })

    describe('when consuming from overflow', () => {
        beforeEach(() => {
            handler = new SessionRecordingRestrictionHandler(
                restrictionManager,
                overflowTopic,
                overflowProducer,
                promiseScheduler,
                true
            )
        })

        it('does not redirect to overflow even when forced', () => {
            const messages: Message[] = [
                createMessage({
                    headers: [{ token: 'overflow-token' }, { distinct_id: 'user-1' }],
                }),
            ]

            jest.mocked(restrictionManager.getAppliedRestrictions).mockReturnValue(
                new Set([Restriction.FORCE_OVERFLOW])
            )

            const result = handler.applyRestrictions(messages)

            expect(result).toEqual(messages)
            expect(SessionRecordingIngesterMetrics.observeOverflowedByRestrictions).not.toHaveBeenCalled()
            expect(promiseScheduler.schedule).not.toHaveBeenCalled()
        })

        it('still drops messages that should be dropped', () => {
            const messages: Message[] = [
                createMessage({
                    headers: [{ token: 'drop-token' }, { distinct_id: 'user-1' }],
                }),
            ]

            jest.mocked(restrictionManager.getAppliedRestrictions).mockReturnValue(new Set([Restriction.DROP_EVENT]))

            const result = handler.applyRestrictions(messages)

            expect(result).toEqual([])
            expect(SessionRecordingIngesterMetrics.observeDroppedByRestrictions).toHaveBeenCalledWith(1)
        })
    })
})
