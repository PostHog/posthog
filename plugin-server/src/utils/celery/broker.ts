import { v4 } from 'uuid'

import { Pausable } from '../../types'
import { DB } from '../db/db'
import { status } from '../status'
import { Message } from './message'

type BrokerSubscription = { queue: string; callback: (message: Message) => any }

class RedisMessage extends Message {
    private raw: Record<string, any>

    constructor(payload: Record<string, any>) {
        super(
            Buffer.from(payload['body'], 'base64'),
            payload['content-type'],
            payload['content-encoding'],
            payload['properties'],
            payload['headers']
        )

        this.raw = payload
    }
}

export class Broker implements Pausable {
    db: DB
    subscriptions: BrokerSubscription[] = []
    channels: Promise<void>[] = []
    closing = false
    paused = false

    /**
     * Redis broker class
     * @constructor RedisBroker
     * @param {DB} db the db object
     */
    constructor(db: DB) {
        this.db = db
    }

    /**
     * @method RedisBroker#disconnect
     * @returns {Promise} promises that continues if redis disconnected.
     */
    public disconnect(): Promise<any> {
        this.closing = true
        return Promise.all(this.channels)
    }

    /**
     * @method RedisBroker#publish
     *
     * @returns {Promise}
     */
    public publish(
        body: Record<string, any> | [Array<any>, Record<string, any>, Record<string, any>],
        exchange: string,
        routingKey: string,
        headers: Record<string, any>,
        properties: Record<string, any>
    ): Promise<number> {
        const messageBody = JSON.stringify(body)
        const contentType = 'application/json'
        const contentEncoding = 'utf-8'
        const message = {
            body: Buffer.from(messageBody).toString('base64'),
            'content-type': contentType,
            'content-encoding': contentEncoding,
            headers,
            properties: {
                body_encoding: 'base64',
                delivery_info: {
                    exchange: exchange,
                    routing_key: routingKey,
                },
                delivery_mode: 2,
                delivery_tag: v4(),
                ...properties,
            },
        }

        return this.db.redisLPush(routingKey, message)
    }

    /**
     * Pause execution of queue. Wait until all channel promises have been exhausted.
     * @method RedisBroker#pause
     *
     * @returns {Promise}
     */
    public async pause(): Promise<void> {
        if (this.paused) {
            return
        }
        const oldChannels = this.channels
        this.paused = true
        this.channels = []
        await Promise.all(oldChannels)
    }

    public resume(): void {
        if (!this.paused) {
            return
        }
        this.paused = false
        for (const { queue, callback } of this.subscriptions) {
            this.channels.push(new Promise((resolve) => this.receiveFast(resolve, queue, callback)))
        }
    }

    public isPaused(): boolean {
        return this.paused
    }

    /**
     * @method RedisBroker#subscribe
     * @param {string} queue
     * @param {Function} callback
     * @returns {Promise}
     */
    public subscribe(queue: string, callback: (message: Message) => any): Promise<any[]> {
        this.subscriptions.push({ queue, callback })
        this.channels.push(new Promise((resolve) => this.receiveFast(resolve, queue, callback)))
        return Promise.all(this.channels)
    }

    /**
     * Ask for the next event the next chance we get.
     * @private
     * @param {Function} resolve
     * @param {string} queue
     * @param {Function} callback
     */
    private receiveFast(resolve: () => void, queue: string, callback: (message: Message) => any): void {
        process.nextTick(() => this.receiveOneOnNextTick(resolve, queue, callback))
    }

    /**
     * Pause 50ms before asking for another event. Used if no event was returned the last time.
     * @private
     * @param {Function} resolve
     * @param {string} queue
     * @param {Function} callback
     */
    private receiveSlow(resolve: () => void, queue: string, callback: (message: Message) => any): void {
        setTimeout(() => this.receiveOneOnNextTick(resolve, queue, callback), 50)
    }

    /**
     * @private
     * @param {Function} resolve
     * @param {String} queue
     * @param {Function} callback
     * @returns {Promise}
     */
    private async receiveOneOnNextTick(
        resolve: () => void,
        queue: string,
        callback: (message: Message) => any
    ): Promise<void> {
        if (this.closing || this.paused) {
            resolve()
            return
        }

        try {
            const body = await this.receiveOne(queue)
            if (body) {
                callback(body)
                this.receiveFast(resolve, queue, callback)
            } else {
                this.receiveSlow(resolve, queue, callback)
            }
        } catch (error) {
            status.error('⚠️', 'An error occured in Celery broker:\n', error)
        }
    }

    /**
     * @private
     * @param {string} celeryQueue
     * @return {Promise}
     */
    private async receiveOne(celeryQueue: string): Promise<Message | null> {
        const result = await this.db.redisBRPop(celeryQueue, '5')

        if (!result || !result[1]) {
            return null
        }

        const [queue, item] = result
        const rawMsg = JSON.parse(item)

        // now supports only application/json of content-type
        if (rawMsg['content-type'] !== 'application/json') {
            throw new Error(`queue ${queue} item: unsupported content type ${rawMsg['content-type']}`)
        }
        // now supports only base64 of body_encoding
        if (rawMsg.properties.body_encoding !== 'base64') {
            throw new Error(`queue ${queue} item: unsupported body encoding ${rawMsg.properties.body_encoding}`)
        }
        // now supports only utf-8 of content-encoding
        if (rawMsg['content-encoding'] !== 'utf-8') {
            throw new Error(`queue ${queue} item: unsupported content encoding ${rawMsg['content-encoding']}`)
        }

        return new RedisMessage(rawMsg)
    }
}
