import { instrument } from './metrics'
import { status } from './status'
import { sleep } from './utils'

export class PeriodicTask {
    public readonly promise: Promise<void>
    private running = true
    private abortController: AbortController

    constructor(public name: string, task: () => Promise<void>, intervalMs: number, minimumWaitMs = 0) {
        this.abortController = new AbortController()

        const abortRequested = new Promise((resolve) => {
            this.abortController.signal.addEventListener('abort', resolve, { once: true })
        })

        this.promise = new Promise(async (resolve, reject) => {
            try {
                status.debug('🔄', 'Periodic task starting...', { task })
                while (!this.abortController.signal.aborted) {
                    const startTimeMs = Date.now()
                    await instrument({ metricName: this.name }, task)
                    const durationMs = Date.now() - startTimeMs
                    const waitTimeMs = Math.max(intervalMs - durationMs, minimumWaitMs)
                    status.debug(
                        '🔄',
                        `Task completed in ${durationMs / 1000}s, next evaluation in ${waitTimeMs / 1000}s`,
                        { task }
                    )
                    await Promise.race([sleep(waitTimeMs), abortRequested])
                }
                status.info('✅', 'Periodic task stopped by request.', { task })
                resolve()
            } catch (error) {
                status.warn('⚠️', 'Error in periodic task!', { task, error })
                reject(error)
            } finally {
                this.running = false
            }
        })
    }

    public isRunning(): boolean {
        return this.running
    }

    public async stop(): Promise<void> {
        this.abortController.abort()
        try {
            await this.promise
        } catch {}
    }
}
