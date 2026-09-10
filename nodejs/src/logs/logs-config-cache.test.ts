import { PostgresRouter } from '~/common/utils/db/postgres'

import { LogsConfigCache } from './logs-config-cache'

describe('LogsConfigCache', () => {
    let query: jest.Mock
    let cache: LogsConfigCache

    beforeEach(() => {
        jest.useFakeTimers()
        query = jest.fn()
        cache = new LogsConfigCache({ query } as unknown as PostgresRouter)
    })

    afterEach(() => {
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it.each([
        ['stored ordered keys', [{ logs_pattern_message_keys: ['text', 'msg'] }], ['text', 'msg']],
        ['an explicitly empty list', [{ logs_pattern_message_keys: [] }], []],
        ['no config row', [], ['message', 'msg', 'event']],
    ])('uses %s without confusing missing configuration with disabled extraction', async (_name, rows, expected) => {
        query.mockResolvedValueOnce({ rows })
        expect(await cache.getPatternMessageKeys(1)).toEqual(expected)
    })

    it('coalesces concurrent refreshes per team and reloads changed settings after the TTL', async () => {
        let resolveFirstTeam!: (result: { rows: { logs_pattern_message_keys: string[] }[] }) => void
        query.mockReturnValueOnce(new Promise((resolve) => (resolveFirstTeam = resolve)))
        query.mockResolvedValueOnce({ rows: [{ logs_pattern_message_keys: ['other'] }] })

        const first = cache.getPatternMessageKeys(1)
        const concurrent = cache.getPatternMessageKeys(1)
        expect(await cache.getPatternMessageKeys(2)).toEqual(['other'])
        expect(query).toHaveBeenCalledTimes(2)

        resolveFirstTeam({ rows: [{ logs_pattern_message_keys: ['text'] }] })
        expect(await Promise.all([first, concurrent])).toEqual([['text'], ['text']])
        jest.advanceTimersByTime(29_999)
        expect(await cache.getPatternMessageKeys(1)).toEqual(['text'])
        expect(query).toHaveBeenCalledTimes(2)

        jest.advanceTimersByTime(1)
        query.mockResolvedValueOnce({ rows: [{ logs_pattern_message_keys: [] }] })
        expect(await Promise.all([cache.getPatternMessageKeys(1), cache.getPatternMessageKeys(1)])).toEqual([[], []])
        expect(query).toHaveBeenCalledTimes(3)
    })

    it.each([undefined, [], ['text']])('backs off after a failed refresh with cached keys %j', async (storedKeys) => {
        if (storedKeys !== undefined) {
            query.mockResolvedValueOnce({ rows: [{ logs_pattern_message_keys: storedKeys }] })
            await cache.getPatternMessageKeys(1)
            jest.advanceTimersByTime(30_000)
        }
        query.mockClear()
        query.mockRejectedValueOnce(new Error('pg down'))
        const expected = storedKeys ?? ['message', 'msg', 'event']
        expect(await Promise.all([cache.getPatternMessageKeys(1), cache.getPatternMessageKeys(1)])).toEqual([
            expected,
            expected,
        ])
        jest.advanceTimersByTime(29_999)
        expect(await cache.getPatternMessageKeys(1)).toEqual(expected)
        expect(query).toHaveBeenCalledTimes(1)

        jest.advanceTimersByTime(1)
        query.mockResolvedValueOnce({ rows: [{ logs_pattern_message_keys: ['recovered'] }] })
        expect(await cache.getPatternMessageKeys(1)).toEqual(['recovered'])
        expect(query).toHaveBeenCalledTimes(2)
    })
})
