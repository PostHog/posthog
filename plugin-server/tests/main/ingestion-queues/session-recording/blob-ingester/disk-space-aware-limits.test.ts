import { statfs } from 'fs/promises'

import { waitForExpect } from '../../../../../functional_tests/expectations'
import { DiskSpaceAwareLimits } from '../../../../../src/main/ingestion-queues/session-recording/blob-ingester/disk-space-aware-limits'

jest.mock('fs/promises', () => ({
    statfs: jest.fn(),
}))

describe('DiskSpaceAwareLimits', () => {
    let diskSpaceAwareLimits: DiskSpaceAwareLimits
    const maxLimit = 1000
    const sessionRecordingLocalDirectory = '/tmp'

    beforeEach(() => {
        ;(statfs as jest.Mock).mockReset()
    })

    describe('idle flush interval', () => {
        it('initializes with the provided idle flush interval', () => {
            diskSpaceAwareLimits = new DiskSpaceAwareLimits(sessionRecordingLocalDirectory, maxLimit, 1, 1)
            expect(diskSpaceAwareLimits.currentIdleFlushInterval).toBe(1)
        })

        it('updates idle flush interval based on available disk space', async () => {
            const mockStatFsResult = (availableSpaceInMB: number) => ({
                bavail: (availableSpaceInMB * 1_000_000) / 4096,
                bsize: 4096,
            })

            ;(statfs as jest.Mock).mockResolvedValue(mockStatFsResult(10_000))
            diskSpaceAwareLimits = new DiskSpaceAwareLimits(sessionRecordingLocalDirectory, maxLimit, maxLimit, 1)

            await waitForExpect(() => {
                expect(diskSpaceAwareLimits.currentIdleFlushInterval).toBe(Math.round(maxLimit * 0.7))
            }, 5000)
        })

        it('updates idle flush interval based on lowest available disk space', async () => {
            const mockStatFsResult = (availableSpaceInMB: number) => ({
                bavail: (availableSpaceInMB * 1_000_000) / 4096,
                bsize: 4096,
            })

            ;(statfs as jest.Mock).mockResolvedValue(mockStatFsResult(4_000))
            diskSpaceAwareLimits = new DiskSpaceAwareLimits(sessionRecordingLocalDirectory, maxLimit, maxLimit, 1)
            await waitForExpect(() => {
                expect(diskSpaceAwareLimits.currentIdleFlushInterval).toBe(Math.round(maxLimit * 0.1))
            }, 5000)
        })
    })

    describe('buffer size', () => {
        it('initializes with max buffer size', () => {
            diskSpaceAwareLimits = new DiskSpaceAwareLimits(sessionRecordingLocalDirectory, maxLimit, 1, 10_000)
            expect(diskSpaceAwareLimits.currentBufferSizeKB).toBe(maxLimit)
        })

        it('updates buffer size based on available disk space', async () => {
            const mockStatFsResult = (availableSpaceInMB: number) => ({
                bavail: (availableSpaceInMB * 1_000_000) / 4096,
                bsize: 4096,
            })

            ;(statfs as jest.Mock).mockResolvedValue(mockStatFsResult(10_000))
            diskSpaceAwareLimits = new DiskSpaceAwareLimits(sessionRecordingLocalDirectory, maxLimit, 1, 1)

            await waitForExpect(() => {
                expect(diskSpaceAwareLimits.currentBufferSizeKB).toBe(Math.round(maxLimit * 0.7))
            }, 5000)
        }, 20000)

        it('updates buffer size based on lowest available disk space', async () => {
            const mockStatFsResult = (availableSpaceInMB: number) => ({
                bavail: (availableSpaceInMB * 1_000_000) / 4096,
                bsize: 4096,
            })

            ;(statfs as jest.Mock).mockResolvedValue(mockStatFsResult(4_000))
            diskSpaceAwareLimits = new DiskSpaceAwareLimits(sessionRecordingLocalDirectory, maxLimit, 1, 1)
            await waitForExpect(() => {
                expect(diskSpaceAwareLimits.currentBufferSizeKB).toBe(Math.round(maxLimit * 0.1))
            }, 5000)
        }, 20000)
    })
})
