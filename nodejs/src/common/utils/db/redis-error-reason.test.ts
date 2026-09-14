import Redis from 'ioredis'
import { createServer } from 'net'

import { redisErrorReason } from './redis-error-reason'

const closedLocalPort = async (): Promise<number> => {
    const server = createServer()
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
    const { port } = server.address() as { port: number }
    await new Promise<void>((resolve) => server.close(() => resolve()))
    return port
}

describe('redisErrorReason', () => {
    test.each<[string, unknown, string | undefined, string]>([
        ['a command timeout on a ready client', new Error('Command timed out'), 'ready', 'timeout'],
        ['a command timeout with no client status', new Error('Command timed out'), undefined, 'timeout'],
        ['a command timeout while the client reconnects', new Error('Command timed out'), 'reconnecting', 'connection'],
        ['a command timeout after the client ended', new Error('Command timed out'), 'end', 'connection'],
        [
            'a refused socket',
            Object.assign(new Error('connect ECONNREFUSED 10.0.0.1:6379'), { code: 'ECONNREFUSED' }),
            'ready',
            'connection',
        ],
        ['a reset socket', Object.assign(new Error('read ECONNRESET'), { code: 'ECONNRESET' }), 'ready', 'connection'],
        ['a closed connection', new Error('Connection is closed.'), 'end', 'connection'],
        [
            'a command aborted by a connection close',
            Object.assign(new Error('Command aborted due to connection close'), { name: 'AbortError' }),
            'reconnecting',
            'connection',
        ],
        [
            'an error reply from the server',
            Object.assign(new Error("OOM command not allowed when used memory > 'maxmemory'."), { name: 'ReplyError' }),
            'ready',
            'reply',
        ],
        ['an unrecognised error', new Error('Redis down'), 'ready', 'other'],
        ['a non-Error value', 'boom', 'ready', 'other'],
    ])('classifies %s', (_, error, status, expected) => {
        expect(redisErrorReason(error, status)).toBe(expected)
    })

    it('classifies a command timeout on a client that cannot reach its server as a connection failure', async () => {
        const client = new Redis({
            host: '127.0.0.1',
            port: await closedLocalPort(),
            lazyConnect: true,
            commandTimeout: 50,
            retryStrategy: () => 20,
            maxRetriesPerRequest: -1,
        })
        client.on('error', () => undefined)
        client.connect().catch(() => undefined)
        try {
            let caught: unknown
            try {
                await client.mget('key')
            } catch (error) {
                caught = error
            }
            expect(String(caught)).toBe('Error: Command timed out')
            expect(redisErrorReason(caught, client.status)).toBe('connection')
        } finally {
            client.disconnect()
        }
    })
})
