import { PostgresRouter } from '~/common/utils/db/postgres'

import { LogsConfigCache } from './logs-config-cache'

describe('LogsConfigCache', () => {
    let query: jest.Mock
    let cache: LogsConfigCache

    beforeEach(() => {
        query = jest.fn()
        cache = new LogsConfigCache({ query } as unknown as PostgresRouter)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('returns the stored keys for a team with a config row', async () => {
        query.mockResolvedValueOnce({ rows: [{ logs_pattern_message_keys: ['text', 'msg'] }] })
        expect(await cache.getPatternMessageKeys(1)).toEqual(['text', 'msg'])
    })

    it('resolves a team with no config row to no keys rather than a built-in default', async () => {
        query.mockResolvedValueOnce({ rows: [] })
        expect(await cache.getPatternMessageKeys(1)).toEqual([])
    })

    it('fails open to no keys when the fetch throws and nothing is cached', async () => {
        query.mockRejectedValueOnce(new Error('pg down'))
        expect(await cache.getPatternMessageKeys(1)).toEqual([])
    })

    it('serves the last-known keys when a later refresh throws', async () => {
        query.mockResolvedValueOnce({ rows: [{ logs_pattern_message_keys: ['text'] }] })
        await cache.getPatternMessageKeys(1)

        jest.spyOn(Date, 'now').mockReturnValue(Date.now() + 60_000)
        query.mockRejectedValueOnce(new Error('pg down'))
        expect(await cache.getPatternMessageKeys(1)).toEqual(['text'])
    })
})
