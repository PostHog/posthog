import { PostgresRouter, PostgresUse } from './db/postgres'
import { MaterializedColumnSlotManager } from './materialized-column-slot-manager'

describe('MaterializedColumnSlotManager', () => {
    let query: jest.Mock
    let postgres: PostgresRouter

    function makeManager(enabled: boolean): MaterializedColumnSlotManager {
        return new MaterializedColumnSlotManager(postgres, enabled)
    }

    beforeEach(() => {
        query = jest.fn()
        postgres = { query } as unknown as PostgresRouter
    })

    describe('when disabled', () => {
        it('getSlots returns [] without querying Postgres', async () => {
            const manager = makeManager(false)

            await expect(manager.getSlots(7)).resolves.toEqual([])
            expect(query).not.toHaveBeenCalled()
        })

        it('getSlotsForTeams returns {} without querying Postgres', async () => {
            const manager = makeManager(false)

            await expect(manager.getSlotsForTeams([7, 8])).resolves.toEqual({})
            expect(query).not.toHaveBeenCalled()
        })
    })

    describe('getSlots', () => {
        it('returns the team configured slots from Postgres', async () => {
            query.mockResolvedValue({
                rows: [
                    { team_id: 7, property_name: 'browser', slot_index: 3, state: 'READY' },
                    { team_id: 7, property_name: 'os', slot_index: 4, state: 'BACKFILL' },
                ],
            })
            const manager = makeManager(true)

            await expect(manager.getSlots(7)).resolves.toEqual([
                { property_name: 'browser', slot_index: 3, state: 'READY' },
                { property_name: 'os', slot_index: 4, state: 'BACKFILL' },
            ])
            expect(query).toHaveBeenCalledTimes(1)
            expect(query.mock.calls[0][0]).toBe(PostgresUse.COMMON_READ)
            expect(query.mock.calls[0][2]).toEqual([[7]])
        })

        it('negatively caches teams with no slots so it does not re-query within the TTL', async () => {
            query.mockResolvedValue({ rows: [] })
            const manager = makeManager(true)

            await expect(manager.getSlots(7)).resolves.toEqual([])
            await expect(manager.getSlots(7)).resolves.toEqual([])
            expect(query).toHaveBeenCalledTimes(1)
        })

        it('propagates the error when the Postgres lookup fails (fails closed, like TeamManager)', async () => {
            query.mockRejectedValue(new Error('connection reset'))
            const manager = makeManager(true)

            // dmat columns are read authoritatively once READY (no JSON fallback), so a load
            // failure must fail the event rather than silently emit it without its column.
            await expect(manager.getSlots(7)).rejects.toThrow('connection reset')
        })
    })

    describe('getSlotsForTeams', () => {
        it('maps each requested team to its slots, with [] for slot-less teams', async () => {
            query.mockResolvedValue({
                rows: [{ team_id: 7, property_name: 'browser', slot_index: 3, state: 'READY' }],
            })
            const manager = makeManager(true)

            await expect(manager.getSlotsForTeams([7, 8])).resolves.toEqual({
                '7': [{ property_name: 'browser', slot_index: 3, state: 'READY' }],
                '8': [],
            })
        })

        it('returns {} for an empty team list without querying', async () => {
            const manager = makeManager(true)

            await expect(manager.getSlotsForTeams([])).resolves.toEqual({})
            expect(query).not.toHaveBeenCalled()
        })

        it('propagates the error when the Postgres lookup fails', async () => {
            query.mockRejectedValue(new Error('connection reset'))
            const manager = makeManager(true)

            await expect(manager.getSlotsForTeams([7, 8])).rejects.toThrow('connection reset')
        })
    })
})
