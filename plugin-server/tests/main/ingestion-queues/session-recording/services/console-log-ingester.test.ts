import { mockProducer, mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import { ConsoleLogsIngester } from '../../../../../src/main/ingestion-queues/session-recording/services/console-logs-ingester'
import { OffsetHighWaterMarker } from '../../../../../src/main/ingestion-queues/session-recording/services/offset-high-water-marker'
import { IncomingRecordingMessage } from '../../../../../src/main/ingestion-queues/session-recording/types'

jest.mock('../../../../../src/utils/logger')

const makeIncomingMessage = (
    data: Record<string, unknown>[],
    consoleLogIngestionEnabled: boolean
): IncomingRecordingMessage => {
    // @ts-expect-error TODO: Fix incorrect underlying types
    return {
        distinct_id: '',
        eventsRange: { start: 0, end: 0 },
        eventsByWindowId: { window_id: data.map((d) => ({ type: 6, timestamp: 0, data: { ...d } })) },
        metadata: {
            lowOffset: 0,
            highOffset: 0,
            partition: 0,
            topic: 'topic',
            timestamp: 0,
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
                        timestamp: '1970-01-01 00:00:00.000',
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
                          "timestamp": "1970-01-01 00:00:00.000",
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
                          "timestamp": "1970-01-01 00:00:00.000",
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
                          "timestamp": "1970-01-01 00:00:00.000",
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
})
