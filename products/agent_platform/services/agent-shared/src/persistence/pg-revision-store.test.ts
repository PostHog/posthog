/**
 * Pure unit tests for the resilient row parsing that keeps one drifted live
 * spec from poisoning a whole bulk read (the regression that silently stopped
 * the cron sweep fleet-wide). No Postgres — `safeRowToRev` is a pure function.
 */

import { safeRowToRev } from './pg-revision-store'

const baseRow = {
    id: '019e8990-0000-7000-8000-000000000001',
    application_id: '019e8990-0000-7000-8000-0000000000aa',
    parent_revision_id: null,
    created_by_id: null,
    created_at: new Date('2026-06-02T00:00:00.000Z'),
    state: 'live',
    bundle_uri: 's3://x/',
    bundle_sha256: null,
    encrypted_env: null,
}

describe('safeRowToRev', () => {
    // Schema drift is tolerated: a valid spec parses; a cron trigger frozen
    // before `prompt`/`name` were required is rejected by the current schema
    // and skipped (null), never thrown.
    it.each<[string, unknown, boolean]>([
        ['valid spec', { model: 'anthropic/claude-sonnet-4-6' }, false],
        [
            'cron trigger missing the now-required prompt',
            { triggers: [{ type: 'cron', config: { name: 'sweep', schedule: '0 9 * * *', timezone: 'UTC' } }] },
            true,
        ],
        [
            'cron trigger missing name',
            { triggers: [{ type: 'cron', config: { schedule: '0 9 * * *', prompt: 'go' } }] },
            true,
        ],
    ])('%s → null=%s', (_label, spec, expectNull) => {
        const rev = safeRowToRev({ ...baseRow, spec })
        if (expectNull) {
            expect(rev).toBeNull()
        } else {
            expect(rev).not.toBeNull()
            expect(rev!.id).toBe(baseRow.id)
        }
    })

    it('re-throws a non-schema error (real bug) instead of swallowing the row', () => {
        // A genuine bug in rowToRev — not schema drift — must surface loudly, not
        // be logged as spec_unparseable and dropped. A null created_at throws a
        // TypeError on .toISOString(), which is not a ZodError.
        expect(() =>
            safeRowToRev({ ...baseRow, created_at: null as unknown as Date, spec: { model: 'test/x' } })
        ).toThrow()
    })

    it('a mixed batch keeps the good rows and drops the bad ones', () => {
        const rows = [
            { ...baseRow, id: 'a', spec: { model: 'test/x' } },
            {
                ...baseRow,
                id: 'b',
                spec: { triggers: [{ type: 'cron', config: { name: 'n', schedule: '* * * * *' } }] },
            },
            { ...baseRow, id: 'c', spec: { model: 'test/y' } },
        ]
        const kept = rows.map(safeRowToRev).filter((r): r is NonNullable<typeof r> => r !== null)
        expect(kept.map((r) => r.id)).toEqual(['a', 'c'])
    })
})
