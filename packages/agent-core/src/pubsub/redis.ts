import Redis from 'ioredis'

import { logger } from '../logger'
import { SessionBus, SessionEvent, SessionEventListener, SessionInputListener, SessionInputMessage } from './types'

export interface RedisSessionBusConfig {
    /** ioredis-compatible URL (e.g. redis://host:6379). */
    url: string
}

/**
 * Redis pub-sub bus, one publish client + one subscribe client. Subscriptions are
 * multiplexed onto the single subscribe connection; channels are tracked by ref-count
 * so we only unsubscribe when the last listener for a channel goes away.
 */
export class RedisSessionBus implements SessionBus {
    private readonly publisher: Redis.Redis
    private readonly subscriber: Redis.Redis
    private readonly channelListeners = new Map<string, Set<(message: string) => void>>()

    constructor(config: RedisSessionBusConfig) {
        this.publisher = new Redis(config.url)
        this.subscriber = new Redis(config.url)
        this.subscriber.on('message', (channel: string, message: string) => {
            const listeners = this.channelListeners.get(channel)
            if (!listeners) {
                return
            }
            for (const listener of listeners) {
                try {
                    listener(message)
                } catch (err) {
                    logger.error('RedisSessionBus listener error', { channel, error: String(err) })
                }
            }
        })
    }

    async publishEvent(sessionId: string, event: SessionEvent): Promise<void> {
        await this.publisher.publish(this.eventChannel(sessionId), JSON.stringify(event))
    }

    async subscribeEvents(sessionId: string, listener: SessionEventListener): Promise<() => Promise<void>> {
        return this.subscribe(this.eventChannel(sessionId), (raw) => {
            listener(JSON.parse(raw) as SessionEvent)
        })
    }

    async publishInput(sessionId: string, message: SessionInputMessage): Promise<void> {
        await this.publisher.publish(this.inputChannel(sessionId), JSON.stringify(message))
    }

    async subscribeInput(sessionId: string, listener: SessionInputListener): Promise<() => Promise<void>> {
        return this.subscribe(this.inputChannel(sessionId), (raw) => {
            listener(JSON.parse(raw) as SessionInputMessage)
        })
    }

    async disconnect(): Promise<void> {
        this.channelListeners.clear()
        await this.publisher.quit()
        await this.subscriber.quit()
    }

    private async subscribe(channel: string, rawListener: (message: string) => void): Promise<() => Promise<void>> {
        let listeners = this.channelListeners.get(channel)
        if (!listeners) {
            listeners = new Set()
            this.channelListeners.set(channel, listeners)
            await this.subscriber.subscribe(channel)
        }
        listeners.add(rawListener)
        return async () => {
            const current = this.channelListeners.get(channel)
            if (!current) {
                return
            }
            current.delete(rawListener)
            if (current.size === 0) {
                this.channelListeners.delete(channel)
                await this.subscriber.unsubscribe(channel)
            }
        }
    }

    private eventChannel(sessionId: string): string {
        return `agent_session:${sessionId}`
    }

    private inputChannel(sessionId: string): string {
        return `agent_session:${sessionId}:input`
    }
}
