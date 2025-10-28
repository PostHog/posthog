/* eslint-disable no-console */
import type { TestWorkerMessage, TestWorkerResponse } from './testWorker'

export class TestWorkerManager {
    private worker: Worker | null = null
    private workerBlobUrl: string | null = null
    private messageId = 0

    async initialize(): Promise<void> {
        try {
            this.worker = await this.createWorker()

            this.worker.addEventListener('message', (event: MessageEvent<TestWorkerResponse>) => {
                const { type, originalMessage, amendedMessage } = event.data

                if (type === 'response') {
                    console.log('[TestWorkerManager] Received response from worker')
                    console.log('[TestWorkerManager] Original:', originalMessage)
                    console.log('[TestWorkerManager] Amended:', amendedMessage)
                }
            })

            this.worker.addEventListener('error', (error) => {
                console.error('[TestWorkerManager] Worker error:', error)
            })

            this.sendTestMessage('Hello from session replay player!')
        } catch (error) {
            console.error('[TestWorkerManager] Failed to initialize worker:', error)
        }
    }

    private async createWorker(): Promise<Worker> {
        // Load the built worker file from /static/testWorker.js
        // The worker is built by esbuild (see build.mjs) in both dev and prod
        // In dev, esbuild watch mode rebuilds it when testWorker.ts changes
        // Workers must be same-origin, so we use Django's origin (localhost:8010)
        // not Vite's origin (localhost:8234)
        const workerUrl = '/static/testWorker.js'
        return new Worker(workerUrl, { type: 'module' })
    }

    sendTestMessage(message: string): void {
        if (!this.worker) {
            console.warn('[TestWorkerManager] Worker not initialized')
            return
        }

        const msg: TestWorkerMessage = {
            type: 'test',
            message,
        }

        console.log('[TestWorkerManager] Sending message to worker:', message)
        this.worker.postMessage(msg)
        this.messageId++
    }

    terminate(): void {
        if (this.worker) {
            console.log('[TestWorkerManager] Terminating worker')
            this.worker.terminate()
            this.worker = null
        }

        if (this.workerBlobUrl) {
            URL.revokeObjectURL(this.workerBlobUrl)
            this.workerBlobUrl = null
        }
    }
}

let workerManager: TestWorkerManager | null = null

export function getTestWorkerManager(): TestWorkerManager {
    if (!workerManager) {
        workerManager = new TestWorkerManager()
    }
    return workerManager
}

export function terminateTestWorker(): void {
    if (workerManager) {
        workerManager.terminate()
        workerManager = null
    }
}
