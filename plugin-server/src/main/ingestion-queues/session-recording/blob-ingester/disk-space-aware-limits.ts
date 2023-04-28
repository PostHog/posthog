import { statfs } from 'fs/promises'

import { status } from '../../../../utils/status'

export class DiskSpaceAwareLimits {
    get currentBufferSizeKB(): number {
        return Math.round(this.maxBufferSize * this.limitsModifier)
    }

    get currentIdleFlushInterval(): number {
        return Math.round(this.maxIdleFlushInterval * this.limitsModifier)
    }

    private readonly sessionRecordingLocalDirectory: string

    private readonly maxBufferSize: number
    private readonly maxIdleFlushInterval: number

    private limitsCheckInterval: NodeJS.Timer | null = null
    private limitsModifier = 1

    constructor(
        sessionRecordingLocalDirectory: string,
        sessionRecordingMaxBufferSizeKB: number,
        idleFlushInterval = 10_000,
        limitsCheckIntervalMillis = 300_000
    ) {
        this.sessionRecordingLocalDirectory = sessionRecordingLocalDirectory

        this.maxBufferSize = sessionRecordingMaxBufferSizeKB

        this.maxIdleFlushInterval = idleFlushInterval

        this.limitsCheckInterval = setInterval(() => this.checkLimits(), limitsCheckIntervalMillis)
    }

    private async checkLimits() {
        try {
            const stats = await statfs(this.sessionRecordingLocalDirectory)
            const availableSpace = stats.bavail * stats.bsize
            const availableSpaceInMB = availableSpace / 1_000_000

            // the disk has 50GB to start with
            let proposedModifier = 1
            if (availableSpaceInMB < 5_000) {
                proposedModifier = 0.1
            } else if (availableSpaceInMB < 10_000) {
                proposedModifier = 0.5
            } else if (availableSpaceInMB < 20_000) {
                proposedModifier = 0.7
            }

            // both change at the same time so if one has change then...
            if (proposedModifier !== this.limitsModifier) {
                this.limitsModifier = proposedModifier
                status.info('🔭', 'DiskSpaceAwareLimits updated limits', {
                    maxLimitsModifier: this.limitsModifier,
                    newBufferSize: this.currentBufferSizeKB,
                    newIdleFlushInterval: this.currentIdleFlushInterval,
                    availableSpaceInMB,
                })
            }
        } catch (e) {
            status.error('🔭', 'DiskSpaceAwareLimits failed to check disk space', e)
        }
    }
}
