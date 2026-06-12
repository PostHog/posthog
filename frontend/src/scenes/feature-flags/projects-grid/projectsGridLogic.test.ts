import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { projectsGridLogic } from './projectsGridLogic'

interface MockRow {
    key: string
    name: string
    flag_id: number
    team_id: number
    filters: { groups: [] }
    active: boolean
}

function buildRow(i: number): MockRow {
    return {
        key: `flag_${i}`,
        name: `Flag ${i}`,
        flag_id: i,
        team_id: 1,
        filters: { groups: [] },
        active: true,
    }
}

describe('projectsGridLogic', () => {
    let logic: ReturnType<typeof projectsGridLogic.build>

    describe('rows and pagination', () => {
        let lastRequestedTeamIds: string | null

        beforeEach(() => {
            lastRequestedTeamIds = null
            useMocks({
                get: {
                    // `keys/` must be registered before the `:key/` sibling route so it isn't
                    // swallowed by the single-segment path parameter.
                    '/api/organizations/:org/feature_flags/keys/': (req) => {
                        lastRequestedTeamIds = req.url.searchParams.get('team_ids')
                        const offset = Number(req.url.searchParams.get('offset') ?? 0)
                        const count = 40
                        const remaining = Math.max(0, count - offset)
                        const pageSize = Math.min(25, remaining)
                        return [
                            200,
                            {
                                count,
                                next: offset + pageSize < count ? 'next' : null,
                                previous: offset > 0 ? 'prev' : null,
                                results: Array.from({ length: pageSize }, (_, i) => buildRow(offset + i + 1)),
                            },
                        ]
                    },
                    '/api/organizations/:org/feature_flags/:key/': [],
                },
            })
            initKeaTests()
            logic = projectsGridLogic()
            logic.mount()
        })

        afterEach(() => logic.unmount())

        it('loads the first page on mount', async () => {
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.flags).toHaveLength(25)
        })

        it('appends rows when loadMoreFlags is dispatched', async () => {
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.loadMoreFlags()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.flags).toHaveLength(40)
            expect(logic.values.flagsHasMore).toBe(false)
        })

        it('resets rows when search changes', async () => {
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.setSearch('flag_1')
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.flags.length).toBeGreaterThan(0)
            expect(logic.values.flagsOffset).toBeLessThanOrEqual(25)
        })

        it('reloads rows from the top when the compared projects change', async () => {
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.loadMoreFlags()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.flagsOffset).toBe(40)

            logic.actions.setPickedTeamIds([2])
            await expectLogic(logic).toFinishAllListeners()
            // The row set changed, so pagination restarts from the first page.
            expect(logic.values.flags).toHaveLength(25)
            expect(logic.values.flagsOffset).toBe(25)
        })

        it('requests keys for the visible columns', async () => {
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.setPickedTeamIds([7, 9])
            await expectLogic(logic).toFinishAllListeners()
            // Current team is always first, followed by the picked teams.
            expect(lastRequestedTeamIds).toBe(`${logic.values.currentTeamId},7,9`)
        })
    })

    describe('sibling queue (serial)', () => {
        let callOrder: string[]
        let inFlight: number
        let maxInFlight: number

        beforeEach(() => {
            callOrder = []
            inFlight = 0
            maxInFlight = 0

            useMocks({
                get: {
                    '/api/organizations/:org/feature_flags/keys/': {
                        count: 3,
                        next: null,
                        previous: null,
                        results: [buildRow(1), buildRow(2), buildRow(3)],
                    },
                    '/api/organizations/:org/feature_flags/:key/': async (req) => {
                        const key = req.params.key as string
                        callOrder.push(key)
                        inFlight += 1
                        maxInFlight = Math.max(maxInFlight, inFlight)
                        await new Promise((r) => setTimeout(r, 1))
                        inFlight -= 1
                        return [200, []]
                    },
                },
            })
            initKeaTests()
            logic = projectsGridLogic()
            logic.mount()
        })

        afterEach(() => logic.unmount())

        it('fetches siblings one at a time, in order', async () => {
            await expectLogic(logic).toFinishAllListeners()
            expect(callOrder).toEqual(['flag_1', 'flag_2', 'flag_3'])
            expect(maxInFlight).toBe(1)
        })

        it('resets sibling queue when search changes', async () => {
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.siblingQueue).toHaveLength(0)

            logic.actions.enqueueSiblingFetches(['flag_x', 'flag_y'])
            logic.actions.setSearch('something')
            expect(logic.values.siblingQueue).toEqual([])
            expect(logic.values.siblingsLoadingKeys).toEqual([])
        })
    })

    describe('picker + localStorage', () => {
        beforeEach(() => {
            localStorage.clear()
            useMocks({
                get: {
                    '/api/organizations/:org/feature_flags/keys/': { count: 0, next: null, previous: null, results: [] },
                    '/api/organizations/:org/feature_flags/:key/': [],
                },
            })
            initKeaTests()
        })

        afterEach(() => {
            if (logic.cache.mounted) {
                logic.unmount()
            }
        })

        it('persists and hydrates pickedTeamIds', async () => {
            logic = projectsGridLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setPickedTeamIds([3, 4])
            expect(logic.values.pickedTeamIds).toEqual([3, 4])

            const teamId = logic.values.currentTeamId
            const stored = localStorage.getItem(`ff-projects-grid.picked-teams.${teamId}`)
            expect(stored).toBe(JSON.stringify([3, 4]))

            logic.unmount()
            logic = projectsGridLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.pickedTeamIds).toEqual([3, 4])
        })

        it('resetPickedTeamIds clears state and storage', async () => {
            logic = projectsGridLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setPickedTeamIds([9])
            logic.actions.resetPickedTeamIds()

            const teamId = logic.values.currentTeamId
            expect(logic.values.pickedTeamIds).toEqual([])
            expect(localStorage.getItem(`ff-projects-grid.picked-teams.${teamId}`)).toBeNull()
        })
    })
})
