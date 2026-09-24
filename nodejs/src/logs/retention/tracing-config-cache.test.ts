import { PostgresRouter } from '~/common/utils/db/postgres'

import { DEFAULT_TRACES_RETENTION_DAYS, TracingConfigCache } from './tracing-config-cache'

describe('TracingConfigCache', () => {
    let query: jest.Mock
    let cache: TracingConfigCache

    beforeEach(() => {
        query = jest.fn()
        cache = new TracingConfigCache({ query } as unknown as PostgresRouter)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('reads the team default from the tracing config', async () => {
        query.mockResolvedValueOnce({ rows: [{ retention_days: 90 }] })
        expect(await cache.getRetentionDays(1)).toBe(90)
    })

    it('falls back to the default when the team has no config row', async () => {
        query.mockResolvedValueOnce({ rows: [] })
        expect(await cache.getRetentionDays(1)).toBe(DEFAULT_TRACES_RETENTION_DAYS)
    })

    it('serves the cached value inside the refresh window', async () => {
        query.mockResolvedValueOnce({ rows: [{ retention_days: 90 }] })
        await cache.getRetentionDays(1)
        await cache.getRetentionDays(1)
        expect(query).toHaveBeenCalledTimes(1)
    })

    it('fails open to the default when the fetch throws and nothing is cached', async () => {
        query.mockRejectedValueOnce(new Error('pg down'))
        expect(await cache.getRetentionDays(1)).toBe(DEFAULT_TRACES_RETENTION_DAYS)
    })

    it('serves the last-known value when a later refresh throws', async () => {
        query.mockResolvedValueOnce({ rows: [{ retention_days: 90 }] })
        await cache.getRetentionDays(1)

        jest.spyOn(Date, 'now').mockReturnValue(Date.now() + 60_000)
        query.mockRejectedValueOnce(new Error('pg down'))
        expect(await cache.getRetentionDays(1)).toBe(90)
    })
})
