import { CONNECTION_RETRY_BACKOFF_MS, withConnectionRetry } from './connection-retry'

function pgError(message: string, code?: string): Error {
    return Object.assign(new Error(message), code ? { code } : {})
}

async function runWithRetry(run: jest.Mock): Promise<unknown> {
    const outcome = withConnectionRetry('ack', run).then(
        (value) => ({ value }),
        (error) => ({ error })
    )
    await jest.runAllTimersAsync()
    return outcome
}

describe('withConnectionRetry', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it.each([
        ['an admin shutdown', pgError('terminating connection due to administrator command', '57P01')],
        ['a connection failure', pgError('connection failure', '08006')],
        ['a reset socket', pgError('read ECONNRESET', 'ECONNRESET')],
        ['a refused connection', pgError('connect ECONNREFUSED 127.0.0.1:6432', 'ECONNREFUSED')],
        ['a terminated client', pgError('Connection terminated unexpectedly')],
    ])('retries %s on a fresh attempt', async (_, error) => {
        const run = jest.fn().mockRejectedValueOnce(error).mockResolvedValueOnce('written')

        expect(await runWithRetry(run)).toEqual({ value: 'written' })
        expect(run).toHaveBeenCalledTimes(2)
    })

    it.each([
        ['a unique violation', pgError('duplicate key value violates unique constraint', '23505')],
        ['a serialization failure', pgError('could not serialize access', '40001')],
        ['a lost lock', pgError('bulkCreateAndCheckIn(precheck) self row matched 0 rows')],
    ])('throws %s without retrying', async (_, error) => {
        const run = jest.fn().mockRejectedValue(error)

        expect(await runWithRetry(run)).toEqual({ error })
        expect(run).toHaveBeenCalledTimes(1)
    })

    it('throws the last dropped-connection error once every backoff is spent', async () => {
        const error = pgError('Connection terminated unexpectedly')
        const run = jest.fn().mockRejectedValue(error)

        expect(await runWithRetry(run)).toEqual({ error })
        expect(run).toHaveBeenCalledTimes(CONNECTION_RETRY_BACKOFF_MS.length + 1)
    })
})
