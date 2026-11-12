import { GetItemCommand } from '@aws-sdk/client-dynamodb'
import { DecryptCommand } from '@aws-sdk/client-kms'

import { TeamMonthKeys, teamMonthKeyExpiresAtMs, teamMonthWrappingContext } from './team-month-keys'

describe('v4 keys', () => {
    const TEAM = 7
    const MONTH = '2026-10'
    const wrapped = Buffer.from('wrapped')
    const stored = { pk: { S: 'team:7' }, sk: { S: `month:${MONTH}` }, wrapped_key: { B: wrapped } }

    function fakes(row: Record<string, any> | undefined, kmsRequestsPerSecond?: number, readBudgetMs?: number) {
        const dynamo = {
            send: jest.fn((command: unknown) => {
                if (command instanceof GetItemCommand) {
                    return Promise.resolve({ Item: row })
                }
                throw new Error('the fetcher never writes a key row')
            }),
        }
        const kms = {
            send: jest.fn((command: unknown) => {
                if (command instanceof DecryptCommand) {
                    expect(command.input.EncryptionContext).toEqual(teamMonthWrappingContext(TEAM, MONTH))
                    return Promise.resolve({ Plaintext: Buffer.alloc(32, 2) })
                }
                throw new Error('the fetcher never generates a key')
            }),
        }
        return { keys: new TeamMonthKeys(dynamo, kms, 'table', 'arn', kmsRequestsPerSecond, readBudgetMs), dynamo, kms }
    }

    it.each([
        ['unwraps a stored key', stored, { status: 'ok', key: Buffer.alloc(32, 2) }, 1],
        // The recorder stores the row before it sends a URL, so no row means it expired: nothing is minted.
        ['finds no key for a month without a row, and reads again next time', undefined, { status: 'missing' }, 2],
        ['holds a tombstone', { ...stored, wrapped_key: undefined, deleted: { BOOL: true } }, { status: 'deleted' }, 1],
    ])('%s', async (_name, row, expected, reads) => {
        const { keys, dynamo } = fakes(row)
        expect(await keys.get(TEAM, MONTH)).toEqual(expected)
        expect(await keys.get(TEAM, MONTH)).toEqual(expected)
        expect(dynamo.send).toHaveBeenCalledTimes(reads)
    })

    const rotated = { ...stored, wrapped_key: { B: Buffer.from('rotated') } }
    const FIVE: number[] = []
    const tombstone = { ...stored, wrapped_key: undefined, deleted: { BOOL: true } }

    it.each([
        ['reuses the plaintext while the row holds the same wrapped key', [stored, stored], ['ok', 'ok'], 1, FIVE],
        ['unwraps again when the row holds another wrapped key', [stored, rotated], ['ok', 'ok'], 2, FIVE],
        ['drops the plaintext at a tombstone', [stored, tombstone, stored], ['ok', 'deleted', 'ok'], 2, FIVE],
        ['drops the plaintext when the row is gone', [stored, undefined, stored], ['ok', 'missing', 'ok'], 2, FIVE],
        ['unwraps again once the plaintext is half an hour old', Array(7).fill(stored), Array(7).fill('ok'), 2, FIVE],
        // The second read reuses the plaintext a second before it is half an hour old.
        [
            'holds a reused plaintext no longer than the plaintext',
            Array(3).fill(stored),
            Array(3).fill('ok'),
            2,
            [1_799_000, 2_000, 0],
        ],
    ])('after the cache lifetime, %s', async (_name, rows, statuses, unwraps, stepsMs) => {
        // lru-cache keeps the clock object it found at import, and fake timers install another one, so the test
        // moves both. lru-cache reads a start time of zero as an entry with no lifetime.
        let cacheClockMs = 1
        const cacheClock = jest.spyOn(performance, 'now').mockImplementation(() => cacheClockMs)
        jest.useFakeTimers()
        try {
            const { keys, dynamo, kms } = fakes(undefined)
            const seen: string[] = []
            for (const row of rows) {
                dynamo.send.mockResolvedValueOnce({ Item: row } as never)
                seen.push((await keys.get(TEAM, MONTH)).status)
                const stepMs = stepsMs[seen.length - 1] ?? 300_001
                cacheClockMs += stepMs
                jest.advanceTimersByTime(stepMs)
            }
            expect(seen).toEqual(statuses)
            expect(dynamo.send).toHaveBeenCalledTimes(rows.length)
            expect(kms.send).toHaveBeenCalledTimes(unwraps)
        } finally {
            jest.useRealTimers()
            cacheClock.mockRestore()
        }
    })

    it.each([
        ['2026-10', '2027-03-01'],
        ['2026-12', '2027-05-01'],
    ])('expires the key rows of %s at 00:00 UTC on %s, as the recorder writes them', (keyMonth, expiresOn) => {
        expect(teamMonthKeyExpiresAtMs(keyMonth)).toBe(Date.parse(`${expiresOn}T00:00:00Z`))
    })

    it('gives up within its budget while it waits for a KMS turn, and makes no KMS call after that', async () => {
        // One request a minute: the first lookup takes the only slot, the next ones wait on the rate limit or the queue.
        const { keys, kms } = fakes(stored, 1 / 60, 50)
        const months = [
            MONTH,
            ...Array.from({ length: 11 }, (_, month) => `2025-${String(month + 1).padStart(2, '0')}`),
        ]
        const lookups = months.map((month) => keys.get(TEAM, month))

        const settled = await Promise.allSettled(lookups)
        await new Promise((resolve) => setImmediate(resolve))

        expect(settled.map((lookup) => lookup.status)).toEqual(['fulfilled', ...Array(11).fill('rejected')])
        expect(kms.send).toHaveBeenCalledTimes(1)
    })

    it('stops a shared read only once every caller waiting on it has stopped', async () => {
        const { keys, dynamo } = fakes(stored)
        let release!: () => void
        dynamo.send.mockImplementation(
            (_command: unknown, options?: { abortSignal?: AbortSignal }) =>
                new Promise((resolve, reject) => {
                    release = () => resolve({ Item: stored })
                    options?.abortSignal?.addEventListener('abort', () => reject(options.abortSignal!.reason))
                }) as any
        )
        const batch = new AbortController()
        const admission = keys.get(TEAM, MONTH, batch.signal)
        const store = keys.get(TEAM, MONTH)
        batch.abort(new Error('budget'))

        await expect(admission).rejects.toThrow('budget')
        release()
        expect(await store).toEqual({ status: 'ok', key: Buffer.alloc(32, 2) })

        const alone = new AbortController()
        const abandoned = keys.get(TEAM, '2026-09', alone.signal)
        alone.abort(new Error('budget'))
        await expect(abandoned).rejects.toThrow('budget')
        const [, readOptions] = dynamo.send.mock.calls[1] as unknown as [unknown, { abortSignal: AbortSignal }]
        expect(readOptions.abortSignal.aborted).toBe(true)
    })
})
