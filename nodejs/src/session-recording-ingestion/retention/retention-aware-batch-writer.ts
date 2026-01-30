import { S3Client } from '@aws-sdk/client-s3'

import { ValidRetentionPeriods } from '../constants'
import { RetentionPeriodToDaysMap } from '../constants'
import { S3SessionBatchFileStorage } from '../sessions/s3-session-batch-writer'
import {
    SessionBatchFileStorage,
    SessionBatchFileWriter,
    WriteSessionData,
    WriteSessionResult,
} from '../sessions/session-batch-file-storage'
import { RetentionPeriod } from '../types'
import { RetentionService } from './retention-service'

class RetentionAwareBatchFileWriter implements SessionBatchFileWriter {
    private writerMap: { [key in RetentionPeriod]: SessionBatchFileWriter | null }

    constructor(
        private readonly retentionService: RetentionService,
        private readonly storageMap: { [key in RetentionPeriod]: SessionBatchFileStorage }
    ) {
        this.writerMap = ValidRetentionPeriods.reduce(
            (writers, retentionPeriod) => {
                writers[retentionPeriod] = null
                return writers
            },
            {} as { [key in RetentionPeriod]: SessionBatchFileWriter | null }
        )
    }

    public async writeSession(sessionData: WriteSessionData): Promise<WriteSessionResult> {
        const retentionPeriod = await this.retentionService.getSessionRetention(
            sessionData.teamId,
            sessionData.sessionId
        )

        let writer = this.writerMap[retentionPeriod]

        if (writer === null) {
            const storage = this.storageMap[retentionPeriod]
            writer = storage.newBatch()
            this.writerMap[retentionPeriod] = writer
        }

        const { bytesWritten, url } = await writer.writeSession(sessionData)

        return {
            bytesWritten,
            url,
            retentionPeriodDays: RetentionPeriodToDaysMap[retentionPeriod],
        }
    }

    public async finish(): Promise<void> {
        await Promise.all(
            ValidRetentionPeriods.map(async (retentionPeriod) => {
                const writer = this.writerMap[retentionPeriod]

                if (writer !== null) {
                    await writer.finish()
                }
            })
        )
    }
}

export class RetentionAwareStorage implements SessionBatchFileStorage {
    private storageMap: { [key in RetentionPeriod]: SessionBatchFileStorage }

    constructor(
        private readonly s3: S3Client,
        private readonly bucket: string,
        private readonly prefix: string,
        private readonly timeout: number = 5000,
        private readonly retentionService: RetentionService
    ) {
        this.storageMap = ValidRetentionPeriods.reduce(
            (storage, retentionPeriod) => {
                storage[retentionPeriod] = new S3SessionBatchFileStorage(
                    this.s3,
                    this.bucket,
                    `${this.prefix}/${retentionPeriod}`,
                    this.timeout
                )
                return storage
            },
            {} as { [key in RetentionPeriod]: SessionBatchFileStorage }
        )
    }

    public newBatch(): RetentionAwareBatchFileWriter {
        return new RetentionAwareBatchFileWriter(this.retentionService, this.storageMap)
    }

    public checkHealth(): Promise<boolean> {
        return this.storageMap[ValidRetentionPeriods[0]].checkHealth()
    }
}
