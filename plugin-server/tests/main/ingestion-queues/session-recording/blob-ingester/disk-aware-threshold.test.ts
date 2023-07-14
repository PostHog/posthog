import { statfs } from 'fs/promises'

import { DiskSpaceAwareThreshold } from '../../../../../src/main/ingestion-queues/session-recording/blob-ingester/disk-aware-threshold'

jest.mock('fs/promises', () => ({
    statfs: jest.fn(),
}))

const mockStatFsResult = (availableSpaceInMB: number) => ({
    bavail: (availableSpaceInMB * 1_000_000) / 4096,
    bsize: 4096,
})

describe('DiskSpaceAwareThreshold', () => {
    let diskSpaceAwareThreshold: DiskSpaceAwareThreshold
    const sessionRecordingLocalDirectory = '/tmp'

    beforeEach(() => {
        ;(statfs as jest.Mock).mockReset()
        jest.useFakeTimers({ legacyFakeTimers: true })
    })

    afterEach(() => {
        jest.runOnlyPendingTimers()
        jest.useRealTimers()
    })

    describe('flush interval', () => {
        it('updates flush int1erval based on qavailable disk space', () => {
            ;(statfs as jest.Mock).mockResolvedValue(mockStatFsResult(20_000))
            diskSpaceAwareThreshold = new DiskSpaceAwareThreshold(sessionRecordingLocalDirectory)
            jest.advanceTimersByTime(60_001)
            expect(diskSpaceAwareThreshold.adjustThreshold(1000)).toBe(1000)
        })

        it('updates flush int1erval based on available disk space', () => {
            ;(statfs as jest.Mock).mockResolvedValue(mockStatFsResult(19_999))
            diskSpaceAwareThreshold = new DiskSpaceAwareThreshold(sessionRecordingLocalDirectory)
            jest.advanceTimersByTime(60_001)
            expect(diskSpaceAwareThreshold.adjustThreshold(1000)).toBe(700)
        })

        it('updates flush interval based on available disk space', () => {
            ;(statfs as jest.Mock).mockResolvedValue(mockStatFsResult(9_999))
            diskSpaceAwareThreshold = new DiskSpaceAwareThreshold(sessionRecordingLocalDirectory)
            jest.advanceTimersByTime(60_001)
            expect(diskSpaceAwareThreshold.adjustThreshold(1000)).toBe(500)
        })

        it('2', () => {
            ;(statfs as jest.Mock).mockResolvedValue(mockStatFsResult(4_999))
            diskSpaceAwareThreshold = new DiskSpaceAwareThreshold(sessionRecordingLocalDirectory)
            jest.advanceTimersByTime(60_001)
            expect(diskSpaceAwareThreshold.adjustThreshold(1000)).toBe(0)
        })
    })
})
