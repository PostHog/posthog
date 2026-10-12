import { DependencyUnavailableError } from '~/common/utils/db/error'
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

    it('rethrows a dependency outage when nothing is cached', async () => {
        query.mockRejectedValueOnce(new DependencyUnavailableError('pg down', 'Postgres', new Error('pg down')))
        await expect(cache.getRetentionDays(1)).rejects.toBeInstanceOf(DependencyUnavailableError)
    })

    it('fails open to the default when the fetch throws another error and nothing is cached', async () => {
        query.mockRejectedValueOnce(new Error('relation "tracing_teamtracingconfig" does not exist'))
        expect(await cache.getRetentionDays(1)).toBe(DEFAULT_TRACES_RETENTION_DAYS)
    })

    it.each([
        ['a dependency outage', new DependencyUnavailableError('pg down', 'Postgres', new Error('pg down'))],
        ['another error', new Error('relation "tracing_teamtracingconfig" does not exist')],
    ])('serves the last-known value when a later refresh hits %s', async (_, error) => {
        query.mockResolvedValueOnce({ rows: [{ retention_days: 90 }] })
        await cache.getRetentionDays(1)

        jest.spyOn(Date, 'now').mockReturnValue(Date.now() + 60_000)
        query.mockRejectedValueOnce(error)
        expect(await cache.getRetentionDays(1)).toBe(90)
    })
})
