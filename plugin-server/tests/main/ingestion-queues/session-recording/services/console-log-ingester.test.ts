import { mockProducer, mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import { ConsoleLogsIngester } from '../../../../../src/main/ingestion-queues/session-recording/services/console-logs-ingester'
import { OffsetHighWaterMarker } from '../../../../../src/main/ingestion-queues/session-recording/services/offset-high-water-marker'
import { IncomingRecordingMessage } from '../../../../../src/main/ingestion-queues/session-recording/types'

jest.mock('../../../../../src/utils/logger')

const makeIncomingMessage = (
    data: Record<string, unknown>[],
    consoleLogIngestionEnabled: boolean,
    timestamp: number = 1704067200000 // 2024-01-01 00:00:00 UTC
): IncomingRecordingMessage => {
    // @ts-expect-error TODO: Fix incorrect underlying types
    return {
        distinct_id: '',
        eventsRange: { start: timestamp, end: timestamp },
        eventsByWindowId: { window_id: data.map((d) => ({ type: 6, timestamp: timestamp, data: { ...d } })) },
        metadata: {
            lowOffset: 0,
            highOffset: 0,
            partition: 0,
            topic: 'topic',
            timestamp: timestamp,
            consoleLogIngestionEnabled,
            rawSize: 0,
        },
        session_id: '',
        team_id: 0,
        snapshot_source: 'should not effect this ingestion route',
    }
}

describe('console log ingester', () => {
    let consoleLogIngester: ConsoleLogsIngester

    beforeEach(() => {
        const mockedHighWaterMarker = { isBelowHighWaterMark: jest.fn() } as unknown as OffsetHighWaterMarker
        consoleLogIngester = new ConsoleLogsIngester(mockProducer, mockedHighWaterMarker)
    })
    describe('when enabled on team', () => {
        test('it truncates large console logs', async () => {
            await consoleLogIngester.consume(
                makeIncomingMessage(
                    [
                        {
                            plugin: 'rrweb/console@1',
                            payload: { level: 'info', payload: ['a'.repeat(3001)] },
                        },
                    ],
                    true
                )
            )

            expect(mockProducerObserver.getProducedKafkaMessagesForTopic('log_entries_test')).toEqual([
                {
                    topic: 'log_entries_test',
                    key: null,
                    headers: undefined,
                    value: {
                        team_id: 0,
                        message: 'a'.repeat(2999),
                        level: 'info',
                        log_source: 'session_replay',
                        log_source_id: '',
                        instance_id: null,
                        timestamp: '2024-01-01 00:00:00.000',
                    },
                },
            ])
        })

        test('it handles multiple console logs', async () => {
            await consoleLogIngester.consume(
                makeIncomingMessage(
                    [
                        {
                            plugin: 'rrweb/console@1',
                            payload: { level: 'info', payload: ['aaaaa'] },
                        },
                        {
                            plugin: 'rrweb/something-else@1',
                            payload: { level: 'info', payload: ['bbbbb'] },
                        },
                        {
                            plugin: 'rrweb/console@1',
                            payload: { level: 'info', payload: ['ccccc'] },
                        },
                    ],
                    true
                )
            )
            expect(mockProducerObserver.produceSpy).toHaveBeenCalledTimes(2)
            expect(mockProducerObserver.getParsedQueuedMessages()).toMatchInlineSnapshot(`
                [
                  {
                    "messages": [
                      {
                        "headers": undefined,
                        "key": null,
                        "value": {
                          "instance_id": null,
                          "level": "info",
                          "log_source": "session_replay",
                          "log_source_id": "",
                          "message": "aaaaa",
                          "team_id": 0,
                          "timestamp": "2024-01-01 00:00:00.000",
                        },
                      },
                    ],
                    "topic": "log_entries_test",
                  },
                  {
                    "messages": [
                      {
                        "headers": undefined,
                        "key": null,
                        "value": {
                          "instance_id": null,
                          "level": "info",
                          "log_source": "session_replay",
                          "log_source_id": "",
                          "message": "ccccc",
                          "team_id": 0,
                          "timestamp": "2024-01-01 00:00:00.000",
                        },
                      },
                    ],
                    "topic": "log_entries_test",
                  },
                ]
            `)
        })

        test('it de-duplicates console logs', async () => {
            await consoleLogIngester.consume(
                makeIncomingMessage(
                    [
                        {
                            plugin: 'rrweb/console@1',
                            payload: { level: 'info', payload: ['aaaaa'] },
                        },
                        {
                            plugin: 'rrweb/console@1',
                            payload: { level: 'info', payload: ['aaaaa'] },
                        },
                    ],
                    true
                )
            )
            expect(mockProducerObserver.getParsedQueuedMessages()).toMatchInlineSnapshot(`
                [
                  {
                    "messages": [
                      {
                        "headers": undefined,
                        "key": null,
                        "value": {
                          "instance_id": null,
                          "level": "info",
                          "log_source": "session_replay",
                          "log_source_id": "",
                          "message": "aaaaa",
                          "team_id": 0,
                          "timestamp": "2024-01-01 00:00:00.000",
                        },
                      },
                    ],
                    "topic": "log_entries_test",
                  },
                ]
            `)
        })
    })

    describe('when disabled on team', () => {
        test('it drops console logs', async () => {
            await consoleLogIngester.consume(makeIncomingMessage([{ plugin: 'rrweb/console@1' }], false))
            expect(mockProducerObserver.produceSpy).not.toHaveBeenCalled()
        })
        test('it does not drop events with no console logs', async () => {
            await consoleLogIngester.consume(makeIncomingMessage([{ plugin: 'some-other-plugin' }], false))
            expect(mockProducerObserver.produceSpy).not.toHaveBeenCalled()
        })
    })

    describe('switchover date', () => {
        const switchoverDate = new Date('2024-01-01T12:00:00.000Z') // 2024-01-01 12:00:00 UTC
        const beforeSwitchover = new Date('2024-01-01T11:59:59.000Z').getTime() // 1 second before
        const atSwitchover = switchoverDate.getTime()
        const afterSwitchover = new Date('2024-01-01T12:00:01.000Z').getTime() // 1 second after

        test('processes all logs when switchover date is null', async () => {
            const ingester = new ConsoleLogsIngester(mockProducer, undefined, null)

            // Create a batch with mixed timestamps
            const messages = [
                makeIncomingMessage(
                    [
                        {
                            plugin: 'rrweb/console@1',
                            payload: { level: 'info', payload: ['before1'] },
                        },
                    ],
                    true,
                    beforeSwitchover
                ),
                makeIncomingMessage(
                    [
                        {
                            plugin: 'rrweb/console@1',
                            payload: { level: 'info', payload: ['at'] },
                        },
                    ],
                    true,
                    atSwitchover
                ),
                makeIncomingMessage(
                    [
                        {
                            plugin: 'rrweb/console@1',
                            payload: { level: 'info', payload: ['after'] },
                        },
                    ],
                    true,
                    afterSwitchover
                ),
                makeIncomingMessage(
                    [
                        {
                            plugin: 'rrweb/console@1',
                            payload: { level: 'info', payload: ['before2'] },
                        },
                    ],
                    true,
                    beforeSwitchover
                ),
            ]

            await ingester.consumeBatch(messages)

            // Should process all messages since switchover is null
            expect(mockProducerObserver.produceSpy).toHaveBeenCalledTimes(4)
            const topicMessages = mockProducerObserver.getParsedQueuedMessages()
            expect(topicMessages).toHaveLength(4)

            // Verify each message's content
            const processedMessages = topicMessages.map((msg) => msg.messages[0].value?.message)
            expect(processedMessages).toEqual(['before1', 'at', 'after', 'before2'])
        })

        test('processes logs before switchover date', async () => {
            const ingester = new ConsoleLogsIngester(mockProducer, undefined, switchoverDate)
            await ingester.consume(
                makeIncomingMessage(
                    [
                        {
                            plugin: 'rrweb/console@1',
                            payload: { level: 'info', payload: ['before'] },
                        },
                    ],
                    true,
                    beforeSwitchover
                )
            )

            expect(mockProducerObserver.produceSpy).toHaveBeenCalledTimes(1)
            const topicMessages = mockProducerObserver.getParsedQueuedMessages()
            expect(topicMessages[0].topic).toEqual('log_entries_test')
            expect(topicMessages[0].messages[0].value?.message).toEqual('before')
        })

        test('drops logs at or after switchover date', async () => {
            const ingester = new ConsoleLogsIngester(mockProducer, undefined, switchoverDate)

            // Test at switchover
            await ingester.consume(
                makeIncomingMessage(
                    [
                        {
                            plugin: 'rrweb/console@1',
                            payload: { level: 'info', payload: ['at'] },
                        },
                    ],
                    true,
                    atSwitchover
                )
            )
            expect(mockProducerObserver.produceSpy).not.toHaveBeenCalled()

            // Test after switchover
            await ingester.consume(
                makeIncomingMessage(
                    [
                        {
                            plugin: 'rrweb/console@1',
                            payload: { level: 'info', payload: ['after'] },
                        },
                    ],
                    true,
                    afterSwitchover
                )
            )
            expect(mockProducerObserver.produceSpy).not.toHaveBeenCalled()
        })

        test('processes mixed batch of logs correctly', async () => {
            const ingester = new ConsoleLogsIngester(mockProducer, undefined, switchoverDate)

            // Create a batch with mixed timestamps
            const messages = [
                makeIncomingMessage(
                    [
                        {
                            plugin: 'rrweb/console@1',
                            payload: { level: 'info', payload: ['before1'] },
                        },
                    ],
                    true,
                    beforeSwitchover
                ),
                makeIncomingMessage(
                    [
                        {
                            plugin: 'rrweb/console@1',
                            payload: { level: 'info', payload: ['at'] },
                        },
                    ],
                    true,
                    atSwitchover
                ),
                makeIncomingMessage(
                    [
                        {
                            plugin: 'rrweb/console@1',
                            payload: { level: 'info', payload: ['after'] },
                        },
                    ],
                    true,
                    afterSwitchover
                ),
                makeIncomingMessage(
                    [
                        {
                            plugin: 'rrweb/console@1',
                            payload: { level: 'info', payload: ['before2'] },
                        },
                    ],
                    true,
                    beforeSwitchover
                ),
            ]

            await ingester.consumeBatch(messages)

            // Should only process the two messages before switchover
            expect(mockProducerObserver.produceSpy).toHaveBeenCalledTimes(2)
            const topicMessages = mockProducerObserver.getParsedQueuedMessages()
            expect(topicMessages).toHaveLength(2)

            // Verify only the before-switchover messages were processed
            const processedMessages = topicMessages.map((msg) => msg.messages[0].value?.message)
            expect(processedMessages).toEqual(['before1', 'before2'])
        })
    })
})
