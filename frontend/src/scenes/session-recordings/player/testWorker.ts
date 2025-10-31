/* eslint-disable no-console */
export interface TestWorkerMessage {
    type: 'test'
    message: string
}

export interface TestWorkerResponse {
    type: 'response'
    originalMessage: string
    amendedMessage: string
}

self.addEventListener('message', (event: MessageEvent<TestWorkerMessage>) => {
    const { type, message } = event.data

    if (type === 'test') {
        console.log('[TestWorker] Received message:', message)

        const amendedMessage = `${message} (processed by worker)`

        const response: TestWorkerResponse = {
            type: 'response',
            originalMessage: message,
            amendedMessage,
        }

        self.postMessage(response)
    }
})

console.log('[TestWorker] Worker initialized and ready')
