import { DependencyUnavailableError } from '~/common/utils/db/error'
import { PostgresRouter } from '~/common/utils/db/postgres'

import { MESSAGE_KEYS } from './log-pattern-mask'
import { PatternMessageKeysCache } from './pattern-message-keys-cache'

describe('PatternMessageKeysCache', () => {
    let query: jest.Mock
    let cache: PatternMessageKeysCache

    beforeEach(() => {
        query = jest.fn()
        cache = new PatternMessageKeysCache({ query } as unknown as PostgresRouter)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it.each([
        ["the team's keys in order", [{ logs_pattern_message_keys: ['log', 'message'] }], ['log', 'message']],
        ['an empty list, so extraction stays off', [{ logs_pattern_message_keys: [] }], []],
        ['the defaults when the team has no config row', [], MESSAGE_KEYS],
    ])('serves %s', async (_, rows, expected) => {
        query.mockResolvedValueOnce({ rows })
        expect(await cache.getMessageKeys(1)).toEqual(expected)
    })

    it('serves cached keys inside the refresh window and picks up saved keys after it', async () => {
        const start = Date.now()
        const now = jest.spyOn(Date, 'now').mockReturnValue(start)
        query.mockResolvedValueOnce({ rows: [{ logs_pattern_message_keys: ['log'] }] })
        expect(await cache.getMessageKeys(1)).toEqual(['log'])

        now.mockReturnValue(start + 29_000)
        expect(await cache.getMessageKeys(1)).toEqual(['log'])
        expect(query).toHaveBeenCalledTimes(1)

        now.mockReturnValue(start + 31_000)
        query.mockResolvedValueOnce({ rows: [{ logs_pattern_message_keys: ['msg'] }] })
        expect(await cache.getMessageKeys(1)).toEqual(['msg'])
        expect(query).toHaveBeenCalledTimes(2)
    })

    it('rethrows a dependency outage when nothing is cached', async () => {
        query.mockRejectedValueOnce(new DependencyUnavailableError('pg down', 'Postgres', new Error('pg down')))
        await expect(cache.getMessageKeys(1)).rejects.toBeInstanceOf(DependencyUnavailableError)
    })

    it('serves the last-known keys after a failed refresh, and waits before querying again', async () => {
        const start = Date.now()
        const now = jest.spyOn(Date, 'now').mockReturnValue(start)
        query.mockResolvedValueOnce({ rows: [{ logs_pattern_message_keys: [] }] })
        await cache.getMessageKeys(1)

        now.mockReturnValue(start + 60_000)
        query.mockRejectedValue(new Error('relation "logs_teamlogsconfig" does not exist'))
        const results = await Promise.all(Array.from({ length: 50 }, () => cache.getMessageKeys(1)))
        expect(results).toEqual(Array(50).fill([]))
        expect(await cache.getMessageKeys(1)).toEqual([])
        expect(query).toHaveBeenCalledTimes(2)

        now.mockReturnValue(start + 66_000)
        query.mockResolvedValueOnce({ rows: [{ logs_pattern_message_keys: ['msg'] }] })
        expect(await cache.getMessageKeys(1)).toEqual(['msg'])
        expect(query).toHaveBeenCalledTimes(3)
    })
})
