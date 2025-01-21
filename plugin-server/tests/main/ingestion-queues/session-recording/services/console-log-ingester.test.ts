import { ConsoleLogsIngester } from '../../../../../src/main/ingestion-queues/session-recording/services/console-logs-ingester'
import { OffsetHighWaterMarker } from '../../../../../src/main/ingestion-queues/session-recording/services/offset-high-water-marker'
import { IncomingRecordingMessage } from '../../../../../src/main/ingestion-queues/session-recording/types'
import { status } from '../../../../../src/utils/status'

jest.mock('../../../../../src/utils/status')

import { getParsedQueuedMessages, mockProducer } from '../../../../helpers/mocks/producer.mock'

const makeIncomingMessage = (
    data: Record<string, unknown>[],
    consoleLogIngestionEnabled: boolean
): IncomingRecordingMessage => {
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
            expect(jest.mocked(status.debug).mock.calls).toEqual([])

            expect(getParsedQueuedMessages()).toEqual([
                {
                    topic: 'log_entries_test',
                    messages: [
                        {
                            key: '',
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
                    ],
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
            expect(jest.mocked(status.debug).mock.calls).toEqual([])
            expect(jest.mocked(mockProducer.queueMessages)).toHaveBeenCalledTimes(1)
            expect(getParsedQueuedMessages()).toEqual([
                {
                    topic: 'log_entries_test',
                    messages: [
                        {
                            key: '',
                            value: {
                                team_id: 0,
                                message: 'aaaaa',
                                level: 'info',
                                log_source: 'session_replay',
                                log_source_id: '',
                                instance_id: null,
                                timestamp: '1970-01-01 00:00:00.000',
                            },
                        },
                        {
                            key: '',
                            value: {
                                team_id: 0,
                                message: 'ccccc',
                                level: 'info',
                                log_source: 'session_replay',
                                log_source_id: '',
                                instance_id: null,
                                timestamp: '1970-01-01 00:00:00.000',
                            },
                        },
                    ],
                },
            ])
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
            expect(jest.mocked(status.debug).mock.calls).toEqual([])
            expect(getParsedQueuedMessages()).toEqual([
                {
                    topic: 'log_entries_test',
                    messages: [
                        {
                            key: '',
                            value: {
                                team_id: 0,
                                message: 'aaaaa',
                                level: 'info',
                                log_source: 'session_replay',
                                log_source_id: '',
                                instance_id: null,
                                timestamp: '1970-01-01 00:00:00.000',
                            },
                        },
                    ],
                },
            ])
        })
    })

    describe('when disabled on team', () => {
        test('it drops console logs', async () => {
            await consoleLogIngester.consume(makeIncomingMessage([{ plugin: 'rrweb/console@1' }], false))
            expect(jest.mocked(mockProducer.queueMessages)).not.toHaveBeenCalled()
        })
        test('it does not drop events with no console logs', async () => {
            await consoleLogIngester.consume(makeIncomingMessage([{ plugin: 'some-other-plugin' }], false))
            expect(jest.mocked(status.debug).mock.calls).toEqual([])
            expect(jest.mocked(mockProducer.queueMessages)).not.toHaveBeenCalled()
        })
    })
})
