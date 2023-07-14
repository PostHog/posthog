import { statfs } from 'fs/promises'

import { status } from '../../../../utils/status'

/**
 * If the underlying disk is filling up we can flush early.
 *
 * We don't need to check disk space every time we want to choose a threshold, so we check it every minute.
 */
export class DiskSpaceAwareThreshold {
    private readonly sessionRecordingLocalDirectory: string
    private availableSpaceInMB: number | null = null

    constructor(sessionRecordingLocalDirectory: string) {
        this.sessionRecordingLocalDirectory = sessionRecordingLocalDirectory

        setInterval(async () => {
            try {
                const stats = await statfs(this.sessionRecordingLocalDirectory)
                const availableSpace = stats.bavail * stats.bsize
                this.availableSpaceInMB = availableSpace / 1_000_000
            } catch (e) {
                status.error('🔭', 'DiskSpaceAwareLimits failed to check disk space', e)
            }
        }, 60_000)
    }

    public adjustThreshold(currentThresholdMillis: number): number {
        let proposedThreshold = currentThresholdMillis

        if (this.availableSpaceInMB !== null) {
            try {
                // the disk has 50GB to start with
                if (this.availableSpaceInMB < 5_000) {
                    proposedThreshold = 0
                } else if (this.availableSpaceInMB < 10_000) {
                    proposedThreshold = currentThresholdMillis * 0.5
                } else if (this.availableSpaceInMB < 20_000) {
                    proposedThreshold = currentThresholdMillis * 0.7
                }

                if (proposedThreshold !== currentThresholdMillis) {
                    status.info('🔭', 'DiskSpaceAwareThreshold adjusted threshold', {
                        startingThreshold: currentThresholdMillis,
                        adjustedThreshold: proposedThreshold,
                        availableSpaceInMB: this.availableSpaceInMB,
                    })
                }
            } catch (e) {
                status.error('🔭', 'DiskSpaceAwareLimits failed to check disk space', e)
            }
        }

        return proposedThreshold
    }
}
