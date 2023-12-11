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
                status.debug('🔄', `${this}: Starting...`)
                while (!this.abortController.signal.aborted) {
                    const startTimeMs = Date.now()
                    await instrument({ metricName: this.name }, task)
                    const durationMs = Date.now() - startTimeMs
                    const waitTimeMs = Math.max(intervalMs - durationMs, minimumWaitMs)
                    status.debug(
                        '🔄',
                        `${this}: Task completed in ${durationMs / 1000}s, next evaluation in ${waitTimeMs / 1000}s`
                    )
                    await Promise.race([sleep(waitTimeMs), abortRequested])
                }
                status.info('🔴', `${this}: Stopped by request.`)
                resolve()
            } catch (error) {
                status.warn('⚠️', `${this}: Unexpected error!`, { error })
                reject(error)
            } finally {
                this.running = false
            }
        })
    }

    public toString(): string {
        return `Periodic Task (${this.name})`
    }

    public isRunning(): boolean {
        return this.running
    }

    public async stop(): Promise<void> {
        status.info(`⏳`, `${this}: Stop requested...`)
        this.abortController.abort()
        try {
            await this.promise
        } catch {}
    }
}
