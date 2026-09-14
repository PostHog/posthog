import { redisErrorReason } from './redis-error-reason'

describe('redisErrorReason', () => {
    test.each<[string, unknown, string]>([
        ['an ioredis command timeout', new Error('Command timed out'), 'timeout'],
        [
            'a refused socket',
            Object.assign(new Error('connect ECONNREFUSED 10.0.0.1:6379'), { code: 'ECONNREFUSED' }),
            'connection',
        ],
        ['a reset socket', Object.assign(new Error('read ECONNRESET'), { code: 'ECONNRESET' }), 'connection'],
        ['a closed connection', new Error('Connection is closed.'), 'connection'],
        [
            'a command aborted by a connection close',
            Object.assign(new Error('Command aborted due to connection close'), { name: 'AbortError' }),
            'connection',
        ],
        [
            'an error reply from the server',
            Object.assign(new Error("OOM command not allowed when used memory > 'maxmemory'."), { name: 'ReplyError' }),
            'reply',
        ],
        ['an unrecognised error', new Error('Redis down'), 'other'],
        ['a non-Error value', 'boom', 'other'],
    ])('classifies %s', (_, error, expected) => {
        expect(redisErrorReason(error)).toBe(expected)
    })
})
