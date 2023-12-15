import { HighLevelProducer } from 'node-rdkafka'

import { defaultConfig } from '../../../../../src/config/config'
import { createKafkaProducer, produce } from '../../../../../src/kafka/producer'
import { ConsoleLogsIngester } from '../../../../../src/main/ingestion-queues/session-recording/services/console-logs-ingester'
import { OffsetHighWaterMarker } from '../../../../../src/main/ingestion-queues/session-recording/services/offset-high-water-marker'
import { IncomingRecordingMessage } from '../../../../../src/main/ingestion-queues/session-recording/types'
import { PluginsServerConfig } from '../../../../../src/types'
import { status } from '../../../../../src/utils/status'

jest.mock('../../../../../src/utils/status')
jest.mock('../../../../../src/kafka/producer')

const makeIncomingMessage = (
    data: Record<string, unknown>[],
    consoleLogIngestionEnabled: boolean
): IncomingRecordingMessage => {
    return {
        distinct_id: '',
        events: data.map((d) => ({ type: 6, timestamp: 0, data: { ...d } })),
        metadata: {
            offset: 0,
            partition: 0,
            topic: 'topic',
            timestamp: 0,
            consoleLogIngestionEnabled,
        },
        session_id: '',
        team_id: 0,
        snapshot_source: 'should not effect this ingestion route',
    }
}

describe('console log ingester', () => {
    let consoleLogIngester: ConsoleLogsIngester
    const mockProducer: jest.Mock = jest.fn()

    beforeEach(async () => {
        mockProducer.mockClear()
        mockProducer['connect'] = jest.fn()

        jest.mocked(createKafkaProducer).mockImplementation(() =>
            Promise.resolve(mockProducer as unknown as HighLevelProducer)
        )

        const mockedHighWaterMarker = { isBelowHighWaterMark: jest.fn() } as unknown as OffsetHighWaterMarker
        consoleLogIngester = new ConsoleLogsIngester({ ...defaultConfig } as PluginsServerConfig, mockedHighWaterMarker)
        await consoleLogIngester.start()
    })
    describe('when enabled on team', () => {
        test('it truncates large console logs', async () => {
            await consoleLogIngester.consume(
                makeIncomingMessage(
                    [
                        {
                            plugin: 'rrweb/console@1',
                            payload: { level: 'log', payload: ['a'.repeat(3001)] },
                        },
                    ],
                    true
                )
            )
            expect(jest.mocked(status.debug).mock.calls).toEqual([])
            expect(jest.mocked(produce).mock.calls).toEqual([
                [
                    {
                        key: '',
                        producer: mockProducer,
                        topic: 'log_entries_test',
                        value: Buffer.from(
                            JSON.stringify({
                                team_id: 0,
                                message: 'a'.repeat(2999),
                                log_level: 'log',
                                log_source: 'session_replay',
                                log_source_id: '',
                                instance_id: null,
                                timestamp: '1970-01-01 00:00:00.000',
                            })
                        ),
                    },
                ],
            ])
        })

        test('it handles multiple console logs', async () => {
            await consoleLogIngester.consume(
                makeIncomingMessage(
                    [
                        {
                            plugin: 'rrweb/console@1',
                            payload: { level: 'log', payload: ['aaaaa'] },
                        },
                        {
                            plugin: 'rrweb/something-else@1',
                            payload: { level: 'log', payload: ['bbbbb'] },
                        },
                        {
                            plugin: 'rrweb/console@1',
                            payload: { level: 'log', payload: ['ccccc'] },
                        },
                    ],
                    true
                )
            )
            expect(jest.mocked(status.debug).mock.calls).toEqual([])
            expect(jest.mocked(produce)).toHaveBeenCalledTimes(2)
            expect(jest.mocked(produce).mock.calls).toEqual([
                [
                    {
                        key: '',
                        producer: mockProducer,
                        topic: 'log_entries_test',
                        value: Buffer.from(
                            JSON.stringify({
                                team_id: 0,
                                message: 'aaaaa',
                                log_level: 'log',
                                log_source: 'session_replay',
                                log_source_id: '',
                                instance_id: null,
                                timestamp: '1970-01-01 00:00:00.000',
                            })
                        ),
                    },
                ],
                [
                    {
                        key: '',
                        producer: mockProducer,
                        topic: 'log_entries_test',
                        value: Buffer.from(
                            JSON.stringify({
                                team_id: 0,
                                message: 'ccccc',
                                log_level: 'log',
                                log_source: 'session_replay',
                                log_source_id: '',
                                instance_id: null,
                                timestamp: '1970-01-01 00:00:00.000',
                            })
                        ),
                    },
                ],
            ])
        })

        test('it de-duplicates console logs', async () => {
            await consoleLogIngester.consume(
                makeIncomingMessage(
                    [
                        {
                            plugin: 'rrweb/console@1',
                            payload: { level: 'log', payload: ['aaaaa'] },
                        },
                        {
                            plugin: 'rrweb/console@1',
                            payload: { level: 'log', payload: ['aaaaa'] },
                        },
                    ],
                    true
                )
            )
            expect(jest.mocked(status.debug).mock.calls).toEqual([])
            expect(jest.mocked(produce).mock.calls).toEqual([
                [
                    {
                        key: '',
                        producer: mockProducer,
                        topic: 'log_entries_test',
                        value: Buffer.from(
                            JSON.stringify({
                                team_id: 0,
                                message: 'aaaaa',
                                log_level: 'log',
                                log_source: 'session_replay',
                                log_source_id: '',
                                instance_id: null,
                                timestamp: '1970-01-01 00:00:00.000',
                            })
                        ),
                    },
                ],
            ])
        })
    })

    describe('when disabled on team', () => {
        test('it drops console logs', async () => {
            await consoleLogIngester.consume(makeIncomingMessage([{ plugin: 'rrweb/console@1' }], false))
            expect(jest.mocked(produce)).not.toHaveBeenCalled()
        })
        test('it does not drop events with no console logs', async () => {
            await consoleLogIngester.consume(makeIncomingMessage([{ plugin: 'some-other-plugin' }], false))
            expect(jest.mocked(status.debug).mock.calls).toEqual([])
            expect(jest.mocked(produce)).not.toHaveBeenCalled()
        })
    })
})
