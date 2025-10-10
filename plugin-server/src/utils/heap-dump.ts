import { S3Client } from '@aws-sdk/client-s3'
import { Upload } from '@aws-sdk/lib-storage'
import { PassThrough } from 'stream'
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

    // Set a timeout for the entire operation (30 minutes for large heap dumps)
    const UPLOAD_TIMEOUT_MS = 30 * 60 * 1000

    try {
        const startTime = Date.now()
        const memoryBefore = process.memoryUsage()
        const heapBefore = v8.getHeapStatistics()

        // If externalMB/arrayBuffersMB grows That's classic V8 off-heap (ArrayBuffer/Buffer) arenas piling up—not JS heap.
        // c.f. https://posthog.slack.com/archives/C06GG249PR6/p1759764183830319
        logger.info('📸 Starting heap dump streaming to S3', {
            filename,
            bucket: s3Bucket,
            memoryUsage: memoryBefore,
            memoryStats: {
                rssMB: Math.round(memoryBefore.rss / 1e6),
                heapUsedMB: Math.round(memoryBefore.heapUsed / 1e6),
                externalMB: Math.round(memoryBefore.external / 1e6),
                arrayBuffersMB: Math.round((memoryBefore.arrayBuffers || 0) / 1e6),
                mallocedMB: Math.round((heapBefore.malloced_memory || 0) / 1e6),
            },
            timeout: `${UPLOAD_TIMEOUT_MS / 1000}s`,
        })

        // Create heap snapshot
        logger.info('📸 Creating heap snapshot...')
        const snapshot = v8.getHeapSnapshot()

        // Create a PassThrough stream similar to session batch writer
        const passThrough = new PassThrough()

        // Pipe snapshot to passThrough - simpler approach
        snapshot.pipe(passThrough)

        snapshot.on('error', (error) => {
            logger.error('📸 Heap snapshot stream error', { error: error.message })
            passThrough.destroy(error)
        })

        snapshot.on('end', () => {
            logger.info('📸 Heap snapshot stream ended')
        })

        passThrough.on('error', (error) => {
            logger.error('📸 PassThrough stream error', { error: error.message })
        })

        logger.info('📸 Heap snapshot created, preparing S3 upload')

        // Stream directly to S3
        const date = new Date().toISOString().split('T')[0]
        const s3Key = `${s3Prefix}/${date}/${filename}`

        logger.info('📸 Initializing S3 upload', {
            bucket: s3Bucket,
            key: s3Key,
        })

        const upload = new Upload({
            client: s3Client,
            params: {
                Bucket: s3Bucket,
                Key: s3Key,
                Body: passThrough, // Use passThrough instead of snapshot directly
                ContentType: 'application/octet-stream',
                Metadata: {
                    podName,
                    pid: process.pid.toString(),
                    timestamp: new Date().toISOString(),
                },
            },
            // Remove partSize and queueSize - let SDK use defaults
        })

        // Add progress tracking
        let lastProgressLog = Date.now()
        let progressCount = 0
        let lastLoaded = 0

        upload.on('httpUploadProgress', (progress) => {
            progressCount++
            const now = Date.now()
            const loaded = progress.loaded || 0
            const total = progress.total || 0
            const percentage = total > 0 ? Math.round((loaded / total) * 100) : 0
            const bytesPerSecond = loaded > lastLoaded ? (loaded - lastLoaded) / ((now - lastProgressLog) / 1000) : 0

            // Log first progress event immediately, then every 5 seconds
            if (progressCount === 1 || now - lastProgressLog > 5000) {
                lastProgressLog = now
                lastLoaded = loaded
                logger.info('📸 Heap dump upload progress', {
                    filename,
                    s3Key,
                    loaded,
                    total,
                    percentage: `${percentage}%`,
                    duration: `${now - startTime}ms`,
                    progressCount,
                    bytesPerSecond: Math.round(bytesPerSecond),
                    part: progress.part,
                })
            }
        })

        try {
            // Create a timeout promise that will abort the upload
            let timeoutId: NodeJS.Timeout | undefined
            const timeoutPromise = new Promise((_, reject) => {
                timeoutId = setTimeout(() => {
                    logger.warn('📸 Heap dump upload timeout - aborting')
                    // Destroy the stream to stop the upload
                    passThrough.destroy()
                    // Abort the upload to free resources
                    void upload.abort().catch((abortError) => {
                        logger.warn('Failed to abort heap dump upload', { error: abortError })
                    })
                    reject(new Error(`Heap dump upload timed out after ${UPLOAD_TIMEOUT_MS / 1000} seconds`))
                }, UPLOAD_TIMEOUT_MS)
            })

            // Race between upload and timeout
            const result = (await Promise.race([upload.done(), timeoutPromise])) as Awaited<
                ReturnType<typeof upload.done>
            >

            // Clear the timeout if upload succeeds
            if (timeoutId) {
                clearTimeout(timeoutId)
            }

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
            const errorMessage = uploadError instanceof Error ? uploadError.message : String(uploadError)
            const errorStack = uploadError instanceof Error ? uploadError.stack : undefined

            logger.error('❌ S3 upload failed during heap dump', {
                error: errorMessage,
                errorStack,
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
