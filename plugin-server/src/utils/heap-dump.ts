import { S3Client } from '@aws-sdk/client-s3'
import { Upload } from '@aws-sdk/lib-storage'
import * as v8 from 'v8'

import { PluginsServerConfig } from '../types'
import { logger } from './logger'

/**
 * Simple heap dump utility based on signal handling
 * Inspired by: https://medium.com/@amirilovic/how-to-find-production-memory-leaks-in-node-js-applications-a1b363b4884f
 *
 * Usage:
 * - Send SIGUSR2 signal to the process: kill -USR2 <pid>
 * - Heap dump will be written to the configured directory
 */

export function initializeHeapDump(config: PluginsServerConfig, heapDumpS3Client?: S3Client): void {
    if (!config.HEAP_DUMP_ENABLED) {
        logger.debug('Heap dump functionality is disabled')
        return
    }

    if (heapDumpS3Client && config.HEAP_DUMP_S3_BUCKET) {
        const s3Bucket = config.HEAP_DUMP_S3_BUCKET
        const s3Prefix = config.HEAP_DUMP_S3_PREFIX
        logger.info('📸 S3 client configured for heap dumps', { bucket: s3Bucket, prefix: s3Prefix })

        // Set up signal handler for SIGUSR2
        process.on('SIGUSR2', () => {
            logger.info('📸 Received SIGUSR2 signal, creating heap dump...')
            createHeapDump(heapDumpS3Client, s3Bucket, s3Prefix).catch((error) => {
                logger.error('❌ Heap dump failed', { error })
            })
        })

        logger.info('📸 Heap dump initialized', {
            bucket: s3Bucket,
            prefix: s3Prefix,
            pid: process.pid,
            instructions: `Send SIGUSR2 signal to create heap dump: kill -USR2 ${process.pid}`,
        })
    } else {
        logger.error('Heap dump S3 client or bucket not provided')
        return
    }
}

export async function createHeapDump(s3Client: S3Client, s3Bucket: string, s3Prefix: string): Promise<void> {
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
    const podName = process.env.POD_NAME || `pid-${process.pid}`
    const filename = `heapdump-${podName}-${timestamp}.heapsnapshot`

    try {
        const startTime = Date.now()
        const memoryBefore = process.memoryUsage()

        logger.info('📸 Starting heap dump streaming to S3', {
            filename,
            bucket: s3Bucket,
            memoryUsage: memoryBefore,
        })

        // Create heap snapshot
        const snapshot = v8.getHeapSnapshot()

        // Stream directly to S3
        const date = new Date().toISOString().split('T')[0]
        const s3Key = `${s3Prefix}/${date}/${filename}`

        const upload = new Upload({
            client: s3Client,
            params: {
                Bucket: s3Bucket,
                Key: s3Key,
                Body: snapshot,
                ContentType: 'application/octet-stream',
                Metadata: {
                    podName,
                    pid: process.pid.toString(),
                    timestamp: new Date().toISOString(),
                },
            },
        })

        try {
            const result = await upload.done()
            const duration = Date.now() - startTime
            const memoryAfter = process.memoryUsage()

            logger.info('✅ Heap dump streamed to S3 successfully', {
                filename,
                s3Key,
                bucket: s3Bucket,
                location: result.Location,
                duration: `${duration}ms`,
                memoryBefore,
                memoryAfter,
                pid: process.pid,
                podName,
            })
        } catch (uploadError) {
            const duration = Date.now() - startTime
            logger.error('❌ S3 upload failed during heap dump', {
                error: uploadError,
                filename,
                s3Key,
                bucket: s3Bucket,
                duration: `${duration}ms`,
                pid: process.pid,
                podName,
            })
            throw uploadError
        }
    } catch (error) {
        logger.error('❌ Failed to stream heap dump to S3', {
            error,
            filename,
            bucket: s3Bucket,
        })
        throw error
    }
}
