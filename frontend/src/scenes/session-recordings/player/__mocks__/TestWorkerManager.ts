export class TestWorkerManager {
    async initialize(): Promise<void> {
        // No-op in tests
    }

    sendTestMessage(): void {
        // No-op in tests
    }

    terminate(): void {
        // No-op in tests
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
