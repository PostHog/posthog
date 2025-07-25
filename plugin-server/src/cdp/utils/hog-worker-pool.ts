import os from 'os'
import path from 'path'
import Piscina from 'piscina'
import { Counter, Histogram } from 'prom-client'

import { logger } from '../../utils/logger'

// Prometheus metrics for monitoring worker performance
export const workerThreadMetrics = {
    executions: new Counter({
        name: 'hog_worker_executions_total',
        help: 'Total number of HogVM executions in worker threads',
        labelNames: ['status'],
    }),

    duration: new Histogram({
        name: 'hog_worker_execution_duration_ms',
        help: 'Time spent executing HogVM in worker threads',
        buckets: [1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500],
    }),

    queueDepth: new Histogram({
        name: 'hog_worker_queue_depth',
        help: 'Number of tasks queued for worker execution',
        buckets: [0, 1, 2, 5, 10, 25, 50, 100],
    }),

    poolUtilization: new Histogram({
        name: 'hog_worker_pool_utilization',
        help: 'Worker pool utilization percentage',
        buckets: [0, 10, 25, 50, 75, 90, 95, 100],
    }),
}

export interface HogWorkerParams {
    bytecode: any
    globals: any
    timeout?: number
    telemetry?: boolean
}

export interface HogWorkerResult {
    success: boolean
    result?: any
    error?: {
        message: string
        name: string
        stack?: string
    }
}

export class HogWorkerPool {
    private pool: Piscina
    private isShuttingDown = false

    constructor(
        options: {
            minThreads?: number
            maxThreads?: number
            idleTimeout?: number
        } = {}
    ) {
        const {
            minThreads = Math.min(2, os.cpus().length),
            maxThreads = Math.min(8, os.cpus().length),
            idleTimeout = 30000, // 30 seconds
        } = options

        logger.info(`Initializing HogWorkerPool with ${minThreads}-${maxThreads} threads`)

        this.pool = new Piscina({
            filename: path.resolve(__dirname, 'hog-worker.js'),
            minThreads,
            maxThreads,
            idleTimeout,
            // Additional Piscina options for performance
            maxQueue: 100, // Limit queue size to prevent memory issues
            concurrentTasksPerWorker: 1, // One task per worker for CPU-intensive work
        })

        // Monitor pool statistics
        this.setupMonitoring()
    }

    /**
     * Execute HogVM bytecode in a worker thread
     */
    async execute(params: HogWorkerParams): Promise<any> {
        if (this.isShuttingDown) {
            throw new Error('Worker pool is shutting down')
        }

        const startTime = Date.now()

        // Record queue depth before execution
        workerThreadMetrics.queueDepth.observe(this.pool.queueSize)

        try {
            const result: HogWorkerResult = await this.pool.run(params)

            const duration = Date.now() - startTime
            workerThreadMetrics.duration.observe(duration)

            if (result.success) {
                workerThreadMetrics.executions.labels({ status: 'success' }).inc()
                return result.result
            } else {
                workerThreadMetrics.executions.labels({ status: 'error' }).inc()
                // Reconstruct error from serialized data
                const error = new Error(result.error?.message || 'Unknown worker error')
                error.name = result.error?.name || 'WorkerError'
                if (result.error?.stack) {
                    error.stack = result.error.stack
                }
                throw error
            }
        } catch (error) {
            const duration = Date.now() - startTime
            workerThreadMetrics.duration.observe(duration)
            workerThreadMetrics.executions.labels({ status: 'error' }).inc()

            logger.error('HogWorkerPool execution failed', {
                error: error.message,
                duration,
                queueSize: this.pool.queueSize,
            })

            throw error
        }
    }

    /**
     * Get pool statistics for monitoring
     */
    getStats() {
        return {
            threads: this.pool.threads.length,
            queue: this.pool.queueSize,
            completed: this.pool.completed,
            utilization: (this.pool.threads.length / this.pool.options.maxThreads!) * 100,
        }
    }

    /**
     * Setup periodic monitoring of pool statistics
     */
    private setupMonitoring() {
        // Update utilization metrics every 30 seconds
        const monitoringInterval = setInterval(() => {
            if (this.isShuttingDown) {
                clearInterval(monitoringInterval)
                return
            }

            const stats = this.getStats()
            workerThreadMetrics.poolUtilization.observe(stats.utilization)

            logger.debug('HogWorkerPool stats', stats)
        }, 30000)

        // Clean up interval on process exit
        process.on('SIGTERM', () => {
            clearInterval(monitoringInterval)
        })
    }

    /**
     * Gracefully shutdown the worker pool
     */
    async shutdown(): Promise<void> {
        if (this.isShuttingDown) {
            return
        }

        this.isShuttingDown = true
        logger.info('Shutting down HogWorkerPool')

        try {
            await this.pool.destroy()
            logger.info('HogWorkerPool shutdown complete')
        } catch (error) {
            logger.error('Error during HogWorkerPool shutdown', { error })
        }
    }
}

// Singleton instance for the behavioral events consumer
let globalWorkerPool: HogWorkerPool | null = null

/**
 * Get or create the global worker pool instance
 */
export function getHogWorkerPool(): HogWorkerPool {
    if (!globalWorkerPool) {
        globalWorkerPool = new HogWorkerPool()

        // Ensure cleanup on process exit
        process.on('SIGTERM', async () => {
            if (globalWorkerPool) {
                await globalWorkerPool.shutdown()
                globalWorkerPool = null
            }
        })

        process.on('SIGINT', async () => {
            if (globalWorkerPool) {
                await globalWorkerPool.shutdown()
                globalWorkerPool = null
            }
        })
    }

    return globalWorkerPool
}
