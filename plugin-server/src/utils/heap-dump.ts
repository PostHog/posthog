import * as fs from 'fs'
import * as path from 'path'
import * as v8 from 'v8'

import { logger } from './logger'

/**
 * Simple heap dump utility based on signal handling
 * Inspired by: https://medium.com/@amirilovic/how-to-find-production-memory-leaks-in-node-js-applications-a1b363b4884f
 *
 * Usage:
 * - Send SIGUSR2 signal to the process: kill -USR2 <pid>
 * - Heap dump will be written to the configured directory
 */

interface HeapDumpConfig {
    enabled: boolean
    outputPath: string
}

let isHeapDumpEnabled = false
let heapDumpOutputPath = '/tmp/heap-dumps'

export function initializeHeapDump(config: HeapDumpConfig): void {
    if (!config.enabled) {
        logger.debug('Heap dump functionality is disabled')
        return
    }

    isHeapDumpEnabled = true
    heapDumpOutputPath = config.outputPath

    // Ensure output directory exists
    try {
        fs.mkdirSync(heapDumpOutputPath, { recursive: true })
    } catch (error) {
        logger.error('Failed to create heap dump directory', { error, path: heapDumpOutputPath })
        return
    }

    // Set up signal handler for SIGUSR2
    process.on('SIGUSR2', () => {
        logger.info('📸 Received SIGUSR2 signal, creating heap dump...')
        createHeapDump()
    })

    logger.info('📸 Heap dump initialized', {
        outputPath: heapDumpOutputPath,
        pid: process.pid,
        instructions: `Send SIGUSR2 signal to create heap dump: kill -USR2 ${process.pid}`,
    })
}

function createHeapDump(): void {
    if (!isHeapDumpEnabled) {
        logger.warn('Heap dump requested but functionality is disabled')
        return
    }

    const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
    const workerId = process.env.WORKER_ID || 'unknown'
    const filename = `heapdump-${workerId}-${process.pid}-${timestamp}.heapsnapshot`
    const filepath = path.join(heapDumpOutputPath, filename)

    try {
        const startTime = Date.now()
        const memoryBefore = process.memoryUsage()

        logger.info('📸 Starting heap dump creation', {
            filename,
            memoryUsage: memoryBefore,
        })

        // Create heap snapshot and write to file
        const snapshot = v8.getHeapSnapshot()
        const fileStream = fs.createWriteStream(filepath)

        snapshot.pipe(fileStream)

        snapshot.on('end', () => {
            const duration = Date.now() - startTime
            const stats = fs.statSync(filepath)
            const memoryAfter = process.memoryUsage()

            logger.info('✅ Heap dump created successfully', {
                filename,
                filepath,
                size: stats.size,
                duration: `${duration}ms`,
                memoryBefore,
                memoryAfter,
                pid: process.pid,
                workerId,
            })
        })

        snapshot.on('error', (error) => {
            logger.error('❌ Failed to create heap dump', {
                error,
                filename,
                filepath,
            })
        })

        fileStream.on('error', (error) => {
            logger.error('❌ Failed to write heap dump to file', {
                error,
                filename,
                filepath,
            })
        })
    } catch (error) {
        logger.error('❌ Unexpected error during heap dump creation', {
            error,
            filename,
            filepath,
        })
    }
}

/**
 * Get current heap dump configuration status
 */
export function getHeapDumpStatus(): {
    enabled: boolean
    outputPath: string
    pid: number
    workerId: string
    instructions: string
} {
    return {
        enabled: isHeapDumpEnabled,
        outputPath: heapDumpOutputPath,
        pid: process.pid,
        workerId: process.env.WORKER_ID || 'unknown',
        instructions: isHeapDumpEnabled
            ? `Send SIGUSR2 signal to create heap dump: kill -USR2 ${process.pid}`
            : 'Heap dumps are disabled',
    }
}
