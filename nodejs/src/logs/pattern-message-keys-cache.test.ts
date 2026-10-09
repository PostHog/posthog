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

    it('rethrows a dependency outage when nothing is cached', async () => {
        query.mockRejectedValueOnce(new DependencyUnavailableError('pg down', 'Postgres', new Error('pg down')))
        await expect(cache.getMessageKeys(1)).rejects.toBeInstanceOf(DependencyUnavailableError)
    })

    it('serves the last-known keys when a later refresh fails', async () => {
        query.mockResolvedValueOnce({ rows: [{ logs_pattern_message_keys: [] }] })
        await cache.getMessageKeys(1)

        jest.spyOn(Date, 'now').mockReturnValue(Date.now() + 60_000)
        query.mockRejectedValueOnce(new Error('relation "logs_teamlogsconfig" does not exist'))
        expect(await cache.getMessageKeys(1)).toEqual([])
    })
})
