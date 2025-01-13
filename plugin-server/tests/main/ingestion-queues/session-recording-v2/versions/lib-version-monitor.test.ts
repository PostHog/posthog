import { MessageHeader } from 'node-rdkafka'

import { MessageWithTeam } from '../../../../../src/main/ingestion-queues/session-recording-v2/teams/types'
import { CaptureIngestionWarningFn } from '../../../../../src/main/ingestion-queues/session-recording-v2/types'
import { LibVersionMonitor } from '../../../../../src/main/ingestion-queues/session-recording-v2/versions/lib-version-monitor'
import { VersionMetrics } from '../../../../../src/main/ingestion-queues/session-recording-v2/versions/version-metrics'

describe('LibVersionMonitor', () => {
    let mockCaptureWarning: jest.MockedFunction<CaptureIngestionWarningFn>
    let mockMetrics: jest.Mocked<VersionMetrics>
    let monitor: LibVersionMonitor

    beforeEach(() => {
        jest.clearAllMocks()
        mockCaptureWarning = jest.fn()
        mockMetrics = {
            incrementLibVersionWarning: jest.fn(),
        } as any
        monitor = new LibVersionMonitor(mockCaptureWarning, mockMetrics)
    })

    describe('parseBatch', () => {
        it('should process messages and return them unmodified', async () => {
            const messages: MessageWithTeam[] = [
                {
                    team: { teamId: 1, consoleLogIngestionEnabled: true },
                    message: {
                        distinct_id: 'test_id',
                        session_id: 'test_session',
                        eventsByWindowId: {},
                        eventsRange: { start: 0, end: 0 },
                        headers: [{ lib_version: '1.74.0' }] as MessageHeader[],
                        metadata: {
                            partition: 0,
                            topic: 'test',
                            rawSize: 0,
                            offset: 0,
                            timestamp: 0,
                        },
                    },
                },
            ]

            const result = await monitor.parseBatch(messages)
            expect(result).toBe(messages)
        })

        it('should trigger warning for old versions', async () => {
            const messages: MessageWithTeam[] = [
                {
                    team: { teamId: 1, consoleLogIngestionEnabled: true },
                    message: {
                        distinct_id: 'test_id',
                        session_id: 'test_session',
                        eventsByWindowId: {},
                        eventsRange: { start: 0, end: 0 },
                        headers: [{ lib_version: '1.74.0' }] as MessageHeader[],
                        metadata: {
                            partition: 0,
                            topic: 'test',
                            rawSize: 0,
                            offset: 0,
                            timestamp: 0,
                        },
                    },
                },
            ]

            await monitor.parseBatch(messages)

            expect(mockMetrics.incrementLibVersionWarning).toHaveBeenCalled()
            expect(mockCaptureWarning).toHaveBeenCalledWith(
                1,
                'replay_lib_version_too_old',
                {
                    libVersion: '1.74.0',
                    parsedVersion: { major: 1, minor: 74 },
                },
                { key: '1.74.0' }
            )
        })

        it('should not trigger warning for newer versions', async () => {
            const messages: MessageWithTeam[] = [
                {
                    team: { teamId: 1, consoleLogIngestionEnabled: true },
                    message: {
                        distinct_id: 'test_id',
                        session_id: 'test_session',
                        eventsByWindowId: {},
                        eventsRange: { start: 0, end: 0 },
                        headers: [{ lib_version: '1.76.0' }] as MessageHeader[],
                        metadata: {
                            partition: 0,
                            topic: 'test',
                            rawSize: 0,
                            offset: 0,
                            timestamp: 0,
                        },
                    },
                },
            ]

            await monitor.parseBatch(messages)

            expect(mockMetrics.incrementLibVersionWarning).not.toHaveBeenCalled()
        })

        it('should handle invalid version formats', async () => {
            const messages: MessageWithTeam[] = [
                {
                    team: { teamId: 1, consoleLogIngestionEnabled: true },
                    message: {
                        distinct_id: 'test_id',
                        session_id: 'test_session',
                        eventsByWindowId: {},
                        eventsRange: { start: 0, end: 0 },
                        headers: [{ lib_version: 'invalid.version' }] as MessageHeader[],
                        metadata: {
                            partition: 0,
                            topic: 'test',
                            rawSize: 0,
                            offset: 0,
                            timestamp: 0,
                        },
                    },
                },
            ]

            await monitor.parseBatch(messages)

            expect(mockMetrics.incrementLibVersionWarning).not.toHaveBeenCalled()
        })

        it('should handle missing version header', async () => {
            const messages: MessageWithTeam[] = [
                {
                    team: { teamId: 1, consoleLogIngestionEnabled: true },
                    message: {
                        distinct_id: 'test_id',
                        session_id: 'test_session',
                        eventsByWindowId: {},
                        eventsRange: { start: 0, end: 0 },
                        headers: [] as MessageHeader[],
                        metadata: {
                            partition: 0,
                            topic: 'test',
                            rawSize: 0,
                            offset: 0,
                            timestamp: 0,
                        },
                    },
                },
            ]

            await monitor.parseBatch(messages)

            expect(mockMetrics.incrementLibVersionWarning).not.toHaveBeenCalled()
        })
    })
})
