import { EventEmitter } from 'node:events'

import { SessionBus, SessionEvent, SessionEventListener, SessionInputListener, SessionInputMessage } from './types'

/**
 * In-process implementation for tests and single-node dev. Not suitable for production
 * because /listen subscribers and the runner generally live in different processes.
 */
export class InMemorySessionBus implements SessionBus {
    private readonly emitter = new EventEmitter()

    constructor() {
        // EventEmitter defaults to 10 listeners. We can plausibly have many concurrent
        // /listen subscribers per session on a busy node, so bump it.
        this.emitter.setMaxListeners(0)
    }

    async publishEvent(sessionId: string, event: SessionEvent): Promise<void> {
        this.emitter.emit(this.eventChannel(sessionId), event)
    }

    async subscribeEvents(sessionId: string, listener: SessionEventListener): Promise<() => Promise<void>> {
        const channel = this.eventChannel(sessionId)
        this.emitter.on(channel, listener)
        return async () => {
            this.emitter.off(channel, listener)
        }
    }

    async publishInput(sessionId: string, message: SessionInputMessage): Promise<void> {
        this.emitter.emit(this.inputChannel(sessionId), message)
    }

    async subscribeInput(sessionId: string, listener: SessionInputListener): Promise<() => Promise<void>> {
        const channel = this.inputChannel(sessionId)
        this.emitter.on(channel, listener)
        return async () => {
            this.emitter.off(channel, listener)
        }
    }

    async disconnect(): Promise<void> {
        this.emitter.removeAllListeners()
    }

    private eventChannel(sessionId: string): string {
        return `agent_session:${sessionId}`
    }

    private inputChannel(sessionId: string): string {
        return `agent_session:${sessionId}:input`
    }
}
