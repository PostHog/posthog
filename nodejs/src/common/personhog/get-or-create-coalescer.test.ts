import { Code, ConnectError } from '@connectrpc/connect'
import { DateTime } from 'luxon'

import { BatchCallFailedError, GetOrCreateCoalescer } from './get-or-create-coalescer'
import { GetOrCreatePersonBatchResult, GetOrCreatePersonEntry, GetOrCreatePersonOutcome } from './identity'

describe('GetOrCreateCoalescer', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })
    afterEach(() => {
        jest.useRealTimers()
    })

    function entry(distinctId: string, setProperties?: Record<string, string>): GetOrCreatePersonEntry {
        return { teamId: 1, distinctId, eventName: '$pageview', createdAtMs: 0, setProperties }
    }

    function found(distinctId: string): GetOrCreatePersonOutcome {
        return {
            created: false,
            person: {
                id: distinctId,
                uuid: `uuid-${distinctId}`,
                team_id: 1,
                created_at: DateTime.fromMillis(0),
                version: 0,
                is_identified: false,
                is_user_id: null,
                last_seen_at: null,
            },
        }
    }

    const echo = (entries: GetOrCreatePersonEntry[]): GetOrCreatePersonBatchResult[] =>
        entries.map((e) => ({ teamId: e.teamId, distinctId: e.distinctId, outcome: found(e.distinctId) }))

    function coalescing(
        answer: (entries: GetOrCreatePersonEntry[]) => GetOrCreatePersonBatchResult[],
        maxBatchBytes: number = 1_000_000
    ) {
        const call = jest.fn(
            (entries: GetOrCreatePersonEntry[]): Promise<GetOrCreatePersonBatchResult[]> =>
                new Promise((resolve) => resolve(answer(entries)))
        )
        const coalescer = new GetOrCreateCoalescer(
            { getOrCreatePersonsByDistinctIds: call },
            { windowMs: 5, maxBatchSize: 3, maxBatchBytes, clientLabel: 'test' }
        )
        return { call, coalescer }
    }

    it('refuses a batch size above the service cap', () => {
        expect(
            () =>
                new GetOrCreateCoalescer(
                    { getOrCreatePersonsByDistinctIds: jest.fn() },
                    { windowMs: 5, maxBatchSize: 251, maxBatchBytes: 1_000_000, clientLabel: 'test' }
                )
        ).toThrow('exceeds the service cap')
    })

    it('sends the entries of one window as one call and answers each caller', async () => {
        const { call, coalescer } = coalescing(echo)

        const first = coalescer.submit(entry('a'))
        const second = coalescer.submit(entry('b'))
        expect(call).not.toHaveBeenCalled()
        await jest.advanceTimersByTimeAsync(5)

        expect(call).toHaveBeenCalledTimes(1)
        expect(call.mock.calls[0][0].map((e) => e.distinctId)).toEqual(['a', 'b'])
        expect((await first).person.id).toBe('a')
        expect((await second).person.id).toBe('b')
    })

    it('sends a full batch without waiting for the window', async () => {
        const { call, coalescer } = coalescing(echo)

        const answers = Promise.all([
            coalescer.submit(entry('a')),
            coalescer.submit(entry('b')),
            coalescer.submit(entry('c')),
        ])

        expect(call).toHaveBeenCalledTimes(1)
        expect((await answers).map((outcome) => outcome.person.id)).toEqual(['a', 'b', 'c'])
    })

    it('closes a batch before an entry takes it over the byte budget', async () => {
        const { call, coalescer } = coalescing(echo, 100)

        const answers = Promise.all([
            coalescer.submit(entry('over-budget-alone', { k: 'x'.repeat(200) })),
            coalescer.submit(entry('b', { k: 'x'.repeat(40) })),
            coalescer.submit(entry('c', { k: 'x'.repeat(40) })),
        ])
        await jest.advanceTimersByTimeAsync(5)

        expect(call.mock.calls.map(([entries]) => entries.map((e) => e.distinctId))).toEqual([
            ['over-budget-alone'],
            ['b', 'c'],
        ])
        expect((await answers).map((outcome) => outcome.person.id)).toEqual(['over-budget-alone', 'b', 'c'])
    })

    it('fails only the entry the service refused', async () => {
        const { coalescer } = coalescing((entries) =>
            entries.map((e) =>
                e.distinctId === 'b'
                    ? { teamId: 1, distinctId: 'b', error: new ConnectError('retry', Code.Aborted) }
                    : { teamId: 1, distinctId: e.distinctId, outcome: found(e.distinctId) }
            )
        )

        const first = coalescer.submit(entry('a'))
        const second = coalescer.submit(entry('b')).catch((error) => error)
        await jest.advanceTimersByTimeAsync(5)

        await expect(first).resolves.toMatchObject({ created: false })
        await expect(second).resolves.toMatchObject({ code: Code.Aborted })
    })

    it('fails every entry of a failed call as a batch failure carrying the cause', async () => {
        const cause = new ConnectError('identity unavailable', Code.Unavailable)
        const { coalescer } = coalescing(() => {
            throw cause
        })

        const failures = [coalescer.submit(entry('a')), coalescer.submit(entry('b'))].map((answer) =>
            answer.catch((error) => error)
        )
        await jest.advanceTimersByTimeAsync(5)

        for (const failure of failures) {
            await expect(failure).resolves.toBeInstanceOf(BatchCallFailedError)
            await expect(failure).resolves.toMatchObject({ cause })
        }
    })

    it.each<[string, (entries: GetOrCreatePersonEntry[]) => GetOrCreatePersonBatchResult[]]>([
        [
            'answers a key that was not asked',
            (entries) => echo(entries).map((result) => ({ ...result, distinctId: `not-${result.distinctId}` })),
        ],
        ['answers in a different order', (entries) => echo(entries).reverse()],
        ['is one result short', (entries) => echo(entries).slice(1)],
    ])('treats a response that %s as a batch failure for every entry', async (_case, answer) => {
        const { coalescer } = coalescing(answer)

        const failures = [coalescer.submit(entry('a')), coalescer.submit(entry('b'))].map((submitted) =>
            submitted.catch((error) => error)
        )
        await jest.advanceTimersByTimeAsync(5)

        for (const failure of failures) {
            await expect(failure).resolves.toBeInstanceOf(BatchCallFailedError)
        }
    })
})
