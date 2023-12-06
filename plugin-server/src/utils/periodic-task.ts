import { status } from './status'
import { sleep } from './utils'

export class PeriodicTask {
    private promise: Promise<void>
    private running = true
    private abortController: AbortController

    constructor(task: () => Promise<void> | void, intervalMs = 1000, minimumWaitMs = 1000) {
        this.abortController = new AbortController()

        const abortRequested = new Promise((resolve) => {
            this.abortController.signal.addEventListener('abort', resolve, { once: true })
        })

        this.promise = new Promise<void>(async (resolve, reject) => {
            try {
                status.debug('🔄', 'Periodic task starting...', { task })
                while (!this.abortController.signal.aborted) {
                    const startTimeMs = +Date.now()
                    await task()
                    const waitTimeMs = Math.max(intervalMs - startTimeMs, minimumWaitMs)
                    status.debug('🔄', `Next evaluation in ${waitTimeMs / 1000}s`, { task })
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
