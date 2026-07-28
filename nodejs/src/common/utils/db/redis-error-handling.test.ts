import type { EventEmitter } from 'events'

import { killGracefully } from '../../utils/utils'
import { captureException } from '../posthog'
import { createRedisClient } from './redis'

// A fake ioredis client we can drive: `createRedisClient` awaits `.info()` then leaves an
// `error` listener attached, so emitting `error` exercises the real handler. Defined inside
// the factory because `jest.mock` is hoisted above module-scope declarations.
jest.mock('ioredis', () => {
    const { EventEmitter: NodeEventEmitter } = require('events')
    return class FakeRedis extends NodeEventEmitter {
        info = jest.fn().mockResolvedValue('')
    }
})
jest.mock('../posthog', () => ({ captureException: jest.fn() }))
jest.mock('../../utils/utils', () => ({
    ...jest.requireActual('../../utils/utils'),
    killGracefully: jest.fn(),
}))

function transientError(): Error {
    return Object.assign(new Error('getaddrinfo ENOTFOUND'), { code: 'ENOTFOUND' })
}

describe('createRedisClient error handling', () => {
    it('does not report transient connection errors while below the kill limit', async () => {
        const redis = (await createRedisClient('redis://localhost:6379')) as unknown as EventEmitter

        for (let i = 0; i < 5; i++) {
            redis.emit('error', transientError())
        }

        // A short DNS/reconnect blip stays a log line, not a captured exception storm.
        expect(captureException).not.toHaveBeenCalled()
        expect(killGracefully).not.toHaveBeenCalled()
    })

    it('still reports unexpected (non-transient) errors immediately', async () => {
        const redis = (await createRedisClient('redis://localhost:6379')) as unknown as EventEmitter

        redis.emit('error', new Error('WRONGTYPE Operation against a key'))

        expect(captureException).toHaveBeenCalledTimes(1)
    })

    it('reports once and kills once when a truly-down Redis crosses the limit, then stays quiet', async () => {
        const redis = (await createRedisClient('redis://localhost:6379')) as unknown as EventEmitter

        // The first 10 are suppressed, the one crossing the limit reports the genuine "Redis is
        // down" signal and kills once, and everything after that stays quiet during shutdown.
        for (let i = 0; i < 20; i++) {
            redis.emit('error', transientError())
        }

        expect(captureException).toHaveBeenCalledTimes(1)
        expect(killGracefully).toHaveBeenCalledTimes(1)
    })
})
