import { S3Client } from '@aws-sdk/client-s3'

import { logger } from '../../../../utils/logger'
import { S3SessionBatchFileStorage } from './s3-session-batch-writer'
import {
    SessionBatchFileStorage,
    SessionBatchFileWriter,
    WriteSessionData,
    WriteSessionResult,
} from './session-batch-file-storage'

/**
 * DualWriteSessionBatchFileWriter
 *
 * Writes session recording batches to both primary and secondary storage simultaneously.
 * This is used during migration from MinIO to LocalStack in local development.
 *
 * Strategy:
 * - Primary storage (MinIO) is blocking - write must succeed
 * - Secondary storage (LocalStack) is non-blocking - failures are logged but don't fail the request
 * - Both writes happen in parallel for better performance
 *
 * ⚠️  FOR LOCAL DEVELOPMENT ONLY ⚠️
 */
class DualWriteSessionBatchFileWriter implements SessionBatchFileWriter {
    private primaryWriter: SessionBatchFileWriter
    private secondaryWriter: SessionBatchFileWriter | null = null
    private secondaryWriteFailed = false

    constructor(primaryWriter: SessionBatchFileWriter, secondaryWriter: SessionBatchFileWriter | null) {
        this.primaryWriter = primaryWriter
        this.secondaryWriter = secondaryWriter

        if (this.secondaryWriter) {
            logger.info('🔄', 'dual_write_session_batch_writer_created', {
                message: 'Dual-write mode enabled - writing to both primary and secondary storage',
            })
        }
    }

    async writeSession(data: WriteSessionData): Promise<WriteSessionResult> {
        // Start both writes in parallel
        const primaryWritePromise = this.primaryWriter.writeSession(data)

        // Secondary write is fire-and-forget - don't wait for it
        if (this.secondaryWriter && !this.secondaryWriteFailed) {
            this.secondaryWriter.writeSession(data).catch((error) => {
                // Log but don't fail the request
                logger.warn('🔄', 'dual_write_secondary_storage_write_failed', {
                    sessionId: data.sessionId,
                    teamId: data.teamId,
                    error: error.message,
                    message: 'Secondary storage write failed (non-critical) - continuing with primary only',
                })
                this.secondaryWriteFailed = true
            })
        }

        // Wait for primary write to complete (must succeed)
        const result = await primaryWritePromise

        return result
    }

    async finish(): Promise<void> {
        // Finish primary storage (blocking)
        await this.primaryWriter.finish()

        // Finish secondary storage (best effort)
        if (this.secondaryWriter && !this.secondaryWriteFailed) {
            await this.secondaryWriter.finish().catch((error) => {
                logger.warn('🔄', 'dual_write_secondary_storage_finish_failed', {
                    error: error.message,
                    message: 'Secondary storage finish failed (non-critical)',
                })
            })
        }

        if (this.secondaryWriter && !this.secondaryWriteFailed) {
            logger.info('🔄', 'dual_write_session_batch_completed', {
                message: 'Successfully wrote to both primary and secondary storage',
            })
        }
    }
}

/**
 * DualWriteSessionBatchFileStorage
 *
 * Factory for creating dual-write session batch writers.
 * Manages both primary and secondary S3 storage backends.
 *
 * ⚠️  FOR LOCAL DEVELOPMENT ONLY ⚠️
 */
export class DualWriteSessionBatchFileStorage implements SessionBatchFileStorage {
    private primaryStorage: S3SessionBatchFileStorage
    private secondaryStorage: S3SessionBatchFileStorage | null = null

    constructor(
        primaryS3Client: S3Client,
        primaryBucket: string,
        primaryPrefix: string,
        primaryTimeout: number,
        secondaryS3Client: S3Client | null,
        secondaryBucket: string,
        secondaryPrefix: string,
        secondaryTimeout: number
    ) {
        this.primaryStorage = new S3SessionBatchFileStorage(
            primaryS3Client,
            primaryBucket,
            primaryPrefix,
            primaryTimeout
        )

        if (secondaryS3Client) {
            this.secondaryStorage = new S3SessionBatchFileStorage(
                secondaryS3Client,
                secondaryBucket,
                secondaryPrefix,
                secondaryTimeout
            )

            logger.info('🔄', 'dual_write_storage_initialized', {
                primaryBucket,
                secondaryBucket,
                message: 'Dual-write storage initialized - session recordings will be written to both storages',
            })
        }
    }

    newBatch(): SessionBatchFileWriter {
        const primaryWriter = this.primaryStorage.newBatch()
        const secondaryWriter = this.secondaryStorage ? this.secondaryStorage.newBatch() : null

        return new DualWriteSessionBatchFileWriter(primaryWriter, secondaryWriter)
    }

    async checkHealth(): Promise<boolean> {
        // Primary storage must be healthy
        const primaryHealthy = await this.primaryStorage.checkHealth()
        if (!primaryHealthy) {
            logger.error('🔄', 'dual_write_primary_storage_unhealthy', {
                message: 'Primary storage health check failed - cannot proceed',
            })
            return false
        }

        // Secondary storage health is informational only
        if (this.secondaryStorage) {
            const secondaryHealthy = await this.secondaryStorage.checkHealth()
            if (!secondaryHealthy) {
                logger.warn('🔄', 'dual_write_secondary_storage_unhealthy', {
                    message: 'Secondary storage health check failed - will continue with primary only',
                })
            } else {
                logger.info('🔄', 'dual_write_health_check_passed', {
                    message: 'Both primary and secondary storage are healthy',
                })
            }
        }

        return true
    }
}
