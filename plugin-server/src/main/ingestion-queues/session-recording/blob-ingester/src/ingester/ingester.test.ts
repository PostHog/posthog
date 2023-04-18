import { beforeEach, expect, it, describe } from 'vitest'
import { Producer } from 'kafkajs'

import { Ingester } from './ingester'
import { createIncomingRecordingMessage } from '../../test/fixtures'

declare module 'vitest' {
    export interface TestContext {
        producer: Producer
    }
}

describe.concurrent('ingester', () => {
    let ingester: Ingester
    beforeEach(async () => {
        ingester = new Ingester()
    })

    it('creates a new session manager if needed', () => {
        const event = createIncomingRecordingMessage()
        ingester.consume(event)
        expect(ingester.sessions.size).toBe(1)
        expect(ingester.sessions.has('1-session_id_1')).toEqual(true)
    })

    it('handles multiple incoming sessions', () => {
        const event = createIncomingRecordingMessage()
        const event2 = createIncomingRecordingMessage({
            session_id: 'session_id_2',
        })
        ingester.consume(event)
        ingester.consume(event2)
        expect(ingester.sessions.size).toBe(2)
        expect(ingester.sessions.has('1-session_id_1')).toEqual(true)
        expect(ingester.sessions.has('1-session_id_2')).toEqual(true)
    })

    it('destroys a session manager if finished', async () => {
        const event = createIncomingRecordingMessage()
        await ingester.consume(event)
        expect(ingester.sessions.has('1-session_id_1')).toEqual(true)
        await ingester.sessions.get('1-session_id_1')?.flush()
        expect(ingester.sessions.has('1-session_id_1')).toEqual(false)
    })

    it.skip('parses incoming kafka messages correctly', () => {})
})
