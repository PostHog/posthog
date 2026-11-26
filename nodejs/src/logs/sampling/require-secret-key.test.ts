import { retryOnDependencyUnavailableError } from '~/common/kafka/error-handling'
import { DependencyUnavailableError } from '~/common/utils/db/error'
import { PostgresRouter } from '~/common/utils/db/postgres'

import type { LogsIngestionMessage } from '../types'
import { compileRuleSet } from './compile-rules'
import { RetryOnDependencyUnavailable, findRequireSecretKeyDrops } from './require-secret-key'
import { SamplingRulesCache } from './sampling-rules-cache'

describe('findRequireSecretKeyDrops', () => {
    let query: jest.Mock
    let cache: SamplingRulesCache

    const requireKeyRule = {
        id: 'require-key',
        rule_type: 'require_secret_key',
        scope_service: null,
        scope_path_pattern: null,
        scope_attribute_filters: [],
        config: {},
        version: '1',
    }
    const outage = (): DependencyUnavailableError =>
        new DependencyUnavailableError('pg down', 'Postgres', new Error('pg down'))
    const message = { teamId: 1, recordCount: 1, bytesUncompressed: 10 } as LogsIngestionMessage
    const noRetry: RetryOnDependencyUnavailable = (fn) => fn()
    const findDrops = (retry = noRetry): ReturnType<typeof findRequireSecretKeyDrops> =>
        findRequireSecretKeyDrops([message], cache, () => true, retry)

    beforeEach(() => {
        query = jest.fn()
        cache = new SamplingRulesCache({ query } as unknown as PostgresRouter)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('fails the batch when the rules fetch is down and no rules are cached', async () => {
        query.mockRejectedValueOnce(outage())

        await expect(findDrops()).rejects.toBeInstanceOf(DependencyUnavailableError)
    })

    it('queries again on the batch retry instead of serving no rules', async () => {
        query.mockRejectedValueOnce(outage())
        await expect(findDrops()).rejects.toBeInstanceOf(DependencyUnavailableError)

        query.mockResolvedValueOnce({ rows: [requireKeyRule] })
        const { dropped } = await findDrops()

        expect(dropped).toEqual(new Set([message]))
    })

    it('retries a transient rules fetch failure in place instead of failing the batch', async () => {
        query.mockRejectedValueOnce(outage()).mockResolvedValueOnce({ rows: [requireKeyRule] })

        const { dropped } = await findDrops((fn) =>
            retryOnDependencyUnavailableError(fn, { retryCount: 2, initialRetryDelayMs: 1 })
        )

        expect(dropped).toEqual(new Set([message]))
    })

    it('drops with the last-known rules when a refresh is down', async () => {
        query.mockResolvedValueOnce({ rows: [requireKeyRule] })
        await findDrops()

        jest.spyOn(Date, 'now').mockReturnValue(Date.now() + 60_000)
        query.mockRejectedValueOnce(outage())
        const { dropped } = await findDrops()

        expect(query).toHaveBeenCalledTimes(2)
        expect(dropped).toEqual(new Set([message]))
    })

    it('leaves the resolve lookup failing open to no rules', async () => {
        query.mockRejectedValueOnce(outage())
        await expect(findDrops()).rejects.toBeInstanceOf(DependencyUnavailableError)

        query.mockResolvedValue({ rows: [requireKeyRule] })
        const compiled = await cache.getCompiledRuleSet(1, 'logs')

        expect(compiled).toEqual(compileRuleSet([]))
    })
})
