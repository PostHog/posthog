import { PostgresRouter } from './db/postgres'
import { MaterializedColumnSlotManager } from './materialized-column-slot-manager'

interface FakeRow {
    team_id: number
    property_name: string
    slot_index: number
    state: 'READY' | 'BACKFILL'
    compaction_target_slot_index: number | null
}

function fakePostgres(rows: FakeRow[]): PostgresRouter {
    return {
        query: jest.fn().mockImplementation((_use: unknown, sql: string, params: [number[]]) => {
            const teamIds = new Set(params[0])
            const matching = rows.filter((r) => teamIds.has(r.team_id))
            return Promise.resolve({ rows: matching, rowCount: matching.length, command: 'SELECT', oid: 0, fields: [] })
        }),
    } as unknown as PostgresRouter
}

describe('MaterializedColumnSlotManager', () => {
    it('returns the slots for a team', async () => {
        const manager = new MaterializedColumnSlotManager(
            fakePostgres([
                {
                    team_id: 1,
                    property_name: 'browser',
                    slot_index: 0,
                    state: 'READY',
                    compaction_target_slot_index: null,
                },
                {
                    team_id: 1,
                    property_name: 'plan',
                    slot_index: 1,
                    state: 'BACKFILL',
                    compaction_target_slot_index: null,
                },
            ])
        )

        const slots = await manager.getSlots(1)

        expect(slots).toEqual([
            {
                property_name: 'browser',
                slot_index: 0,
                state: 'READY',
                compaction_target_slot_index: null,
            },
            {
                property_name: 'plan',
                slot_index: 1,
                state: 'BACKFILL',
                compaction_target_slot_index: null,
            },
        ])
    })

    it('returns an empty array when the team has no slots', async () => {
        const manager = new MaterializedColumnSlotManager(fakePostgres([]))

        await expect(manager.getSlots(42)).resolves.toEqual([])
    })

    it('isolates slots by team', async () => {
        const manager = new MaterializedColumnSlotManager(
            fakePostgres([
                {
                    team_id: 1,
                    property_name: 'browser',
                    slot_index: 0,
                    state: 'READY',
                    compaction_target_slot_index: null,
                },
                {
                    team_id: 2,
                    property_name: 'plan',
                    slot_index: 0,
                    state: 'READY',
                    compaction_target_slot_index: null,
                },
            ])
        )

        const result = await manager.getSlotsForTeams([1, 2])

        expect(result['1']).toEqual([
            {
                property_name: 'browser',
                slot_index: 0,
                state: 'READY',
                compaction_target_slot_index: null,
            },
        ])
        expect(result['2']).toEqual([
            {
                property_name: 'plan',
                slot_index: 0,
                state: 'READY',
                compaction_target_slot_index: null,
            },
        ])
    })

    it('issues the read against COMMON_READ with state and slot_index filters', async () => {
        const postgres = fakePostgres([])
        const manager = new MaterializedColumnSlotManager(postgres)

        await manager.getSlots(1)

        const queryFn = postgres.query as jest.Mock
        expect(queryFn).toHaveBeenCalledTimes(1)
        const sql = queryFn.mock.calls[0][1] as string
        // The query intentionally filters PENDING/ERROR slots out — they must not write to dmat
        // columns since their slot_index is either unassigned or quiesced.
        expect(sql).toContain("s.state IN ('READY', 'BACKFILL')")
        expect(sql).toContain('s.slot_index IS NOT NULL')
        // Property name is read off posthog_propertydefinition rather than denormalized on the slot row.
        expect(sql).toContain('JOIN posthog_propertydefinition pd')
    })
})
