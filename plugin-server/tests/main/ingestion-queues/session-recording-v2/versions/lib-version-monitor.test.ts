import { MessageWithTeam } from '../../../../../src/main/ingestion-queues/session-recording-v2/teams/types'
import { LibVersionMonitor } from '../../../../../src/main/ingestion-queues/session-recording-v2/versions/lib-version-monitor'
import { VersionMetrics } from '../../../../../src/main/ingestion-queues/session-recording-v2/versions/version-metrics'

describe('LibVersionMonitor', () => {
    let monitor: LibVersionMonitor
    let mockCaptureWarning: jest.Mock
    let mockVersionMetrics: jest.Mocked<VersionMetrics>

    beforeEach(() => {
        mockCaptureWarning = jest.fn()
        mockVersionMetrics = {
            incrementLibVersionWarning: jest.fn(),
        } as unknown as jest.Mocked<VersionMetrics>
        monitor = new LibVersionMonitor(mockCaptureWarning, mockVersionMetrics)
    })

    const createMessage = (headers: any[] = []): MessageWithTeam => ({
        team: { teamId: 1, consoleLogIngestionEnabled: false },
        message: {
            metadata: {
                partition: 1,
                topic: 'test-topic',
                offset: 1,
                timestamp: 1234567890,
                rawSize: 100,
            },
            headers,
            distinct_id: 'distinct_id',
            session_id: 'session1',
            eventsByWindowId: { window1: [] },
            eventsRange: { start: 0, end: 0 },
        },
    })

    it('should warn on old lib version (< 1.75.0)', async () => {
        const message = createMessage([{ lib_version: '1.74.0' }])
        const result = await monitor.processBatch([message])

        expect(result).toEqual([message])
        expect(mockVersionMetrics.incrementLibVersionWarning).toHaveBeenCalled()
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

    it('should not warn on new lib version (>= 1.75.0)', async () => {
        const message = createMessage([{ lib_version: '1.75.0' }])
        const result = await monitor.processBatch([message])

        expect(result).toEqual([message])
        expect(mockVersionMetrics.incrementLibVersionWarning).not.toHaveBeenCalled()
        expect(mockCaptureWarning).not.toHaveBeenCalled()
    })

    it('should handle invalid lib version', async () => {
        const message = createMessage([{ lib_version: 'invalid' }])
        const result = await monitor.processBatch([message])

        expect(result).toEqual([message])
        expect(mockVersionMetrics.incrementLibVersionWarning).not.toHaveBeenCalled()
        expect(mockCaptureWarning).not.toHaveBeenCalled()
    })

    it('should handle missing lib version', async () => {
        const message = createMessage()
        const result = await monitor.processBatch([message])

        expect(result).toEqual([message])
        expect(mockVersionMetrics.incrementLibVersionWarning).not.toHaveBeenCalled()
        expect(mockCaptureWarning).not.toHaveBeenCalled()
    })
})
