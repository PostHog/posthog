import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { organizationLogic } from 'scenes/organizationLogic'

import { initKeaTests } from '~/test/init'

import { crossProjectDashboardLogic } from './crossProjectDashboardLogic'
import {
    crossProjectDashboardsDestroy,
    crossProjectDashboardsPartialUpdate,
    crossProjectDashboardsRetrieve,
    crossProjectDashboardsTilesPartialUpdate,
} from './generated/api'

jest.mock('lib/lemon-ui/LemonDialog', () => ({ LemonDialog: { open: jest.fn() } }))

jest.mock('./generated/api', () => ({
    __esModule: true,
    crossProjectDashboardsDestroy: jest.fn(),
    crossProjectDashboardsRetrieve: jest.fn(),
    crossProjectDashboardsPartialUpdate: jest.fn(),
    crossProjectDashboardsTilesDestroy: jest.fn(),
    crossProjectDashboardsTilesPartialUpdate: jest.fn(),
}))

const mockedDialogOpen = LemonDialog.open as jest.Mock
const mockedDestroy = crossProjectDashboardsDestroy as jest.Mock
const mockedRetrieve = crossProjectDashboardsRetrieve as jest.Mock
const mockedPartialUpdate = crossProjectDashboardsPartialUpdate as jest.Mock
const mockedTilePartialUpdate = crossProjectDashboardsTilesPartialUpdate as jest.Mock

const DASHBOARD_ID = '01a0f19d-1c44-715a-a679-188869bd033f'

const TILE = { id: 'tile-1', project_id: 53, insight_id: 266, layouts: {}, color: null, filters_overrides: {} }

const dashboardWith = (filters: Record<string, unknown>): Record<string, unknown> => ({
    id: DASHBOARD_ID,
    name: 'Pageviews across projects',
    filters,
    tiles: [TILE],
})

describe('crossProjectDashboardLogic', () => {
    let logic: ReturnType<typeof crossProjectDashboardLogic.build>

    // The mock persists what it was sent, so a reload reads back the saved filters as the API would.
    let stored: Record<string, unknown> = {}

    const mountWith = async (filters: Record<string, unknown>): Promise<void> => {
        stored = filters
        logic = crossProjectDashboardLogic({ id: DASHBOARD_ID })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        mockedDialogOpen.mockReset()
        mockedDestroy.mockReset()
        mockedRetrieve.mockReset()
        mockedPartialUpdate.mockReset()
        mockedTilePartialUpdate.mockReset()
        mockedTilePartialUpdate.mockImplementation(async (_org, _id, tileId, body) => ({
            ...TILE,
            id: tileId,
            ...body,
        }))
        stored = {}
        mockedRetrieve.mockImplementation(async () => dashboardWith(stored))
        mockedPartialUpdate.mockImplementation(async (_org, _id, body) => {
            stored = body.filters
            return dashboardWith(stored)
        })
        initKeaTests()
        organizationLogic.mount()
        organizationLogic.actions.loadCurrentOrganizationSuccess({ id: 'org-1', name: 'Org' } as any)
    })

    afterEach(() => {
        logic?.unmount()
    })

    // A date change must not clobber the rest of the blob, and must not write a bound nobody chose:
    // the backend also stores property filters here, and a null bound would override each insight's own.
    it.each([
        ['drops the bound that was not chosen', {}, '-7d', null, { date_from: '-7d' }],
        ['replaces a previous range', { date_from: '-30d' }, '-7d', null, { date_from: '-7d' }],
        [
            'keeps filters it does not own',
            { properties: [{ type: 'event', key: 'browser', value: 'Chrome' }] },
            '-7d',
            null,
            { properties: [{ type: 'event', key: 'browser', value: 'Chrome' }], date_from: '-7d' },
        ],
        ['clears both bounds', { date_from: '-7d', date_to: '-1d' }, null, null, {}],
        [
            'writes an explicit range',
            {},
            '2026-01-01',
            '2026-01-31',
            { date_from: '2026-01-01', date_to: '2026-01-31' },
        ],
    ])('setDates %s', async (_name, existing, dateFrom, dateTo, expected) => {
        await mountWith(existing as Record<string, unknown>)

        logic.actions.setDates(dateFrom as string | null, dateTo as string | null)
        await expectLogic(logic).toFinishAllListeners()

        expect(mockedPartialUpdate).toHaveBeenCalledTimes(1)
        expect(mockedPartialUpdate.mock.calls[0][2]).toEqual({ filters: expected })
    })

    it('puts the saved filters in state, so the tiles refetch on the new range', async () => {
        await mountWith({})

        logic.actions.setDates('-7d', null)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.dashboardFilters).toEqual({ date_from: '-7d' })
    })

    it('keeps both of two quick filter edits instead of letting the second overwrite the first', async () => {
        await mountWith({})

        logic.actions.setDates('-7d', null)
        logic.actions.setInterval('week')
        await expectLogic(logic).toFinishAllListeners()

        expect(mockedPartialUpdate).toHaveBeenLastCalledWith('org-1', DASHBOARD_ID, {
            filters: { date_from: '-7d', interval: 'week' },
        })
        expect(logic.values.dashboardFilters).toEqual({ date_from: '-7d', interval: 'week' })
    })
    it.each([
        [
            'a tile override',
            (l: typeof logic) => l.actions.setTileOverride('tile-1', { date_from: '-7d' }),
            { filters_overrides: { date_from: '-7d' } },
        ],
        ['a tile color', (l: typeof logic) => l.actions.setTileColor('tile-1', 'green'), { color: 'green' }],
    ])('saves %s on the tile and updates it in place, without reloading', async (_label, act, body) => {
        await mountWith({})
        expect(mockedRetrieve).toHaveBeenCalledTimes(1)

        act(logic)
        await expectLogic(logic).toFinishAllListeners()

        expect(mockedTilePartialUpdate).toHaveBeenCalledWith('org-1', DASHBOARD_ID, 'tile-1', body)
        expect(mockedRetrieve).toHaveBeenCalledTimes(1)
        expect(logic.values.tiles[0]).toMatchObject(body)
    })
    it.each([
        ['opens the cross-project tab of the dashboards page', async () => undefined, true],
        [
            'stays on the dashboard when the delete fails',
            async () => {
                throw { detail: 'You cannot delete this dashboard.' }
            },
            false,
        ],
    ])('a confirmed delete %s', async (_label, destroy, navigates) => {
        mockedDestroy.mockImplementation(destroy)
        await mountWith({})

        logic.actions.deleteDashboard()
        expect(mockedDestroy).not.toHaveBeenCalled()
        await mockedDialogOpen.mock.calls[0][0].primaryButton.onClick().catch(() => {})

        expect(mockedDestroy).toHaveBeenCalledWith('org-1', DASHBOARD_ID)
        expect(router.values.location.pathname.endsWith('/dashboard')).toBe(navigates)
        expect(router.values.searchParams.tab).toEqual(navigates ? 'cross-project' : undefined)
    })
    const MOVED = { sm: [{ i: 'tile-1', x: 6, y: 0, w: 6, h: 5 }] }

    it.each([
        ['Save layout writes the move once and leaves edit mode', 'saveLayout', true, { x: 6, y: 0 }],
        ['Cancel writes nothing and puts the tile back', 'cancelLayoutEdit', false, { x: 0, y: 0 }],
    ] as const)('%s', async (_label, finish, writes, gridPosition) => {
        await mountWith({})
        logic.actions.enterLayoutEdit()
        logic.actions.setPendingLayouts(MOVED)
        await expectLogic(logic).toFinishAllListeners()
        expect(mockedTilePartialUpdate).not.toHaveBeenCalled()

        logic.actions[finish]()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockedTilePartialUpdate).toHaveBeenCalledTimes(writes ? 1 : 0)
        expect(mockedRetrieve).toHaveBeenCalledTimes(1)
        expect(logic.values.layoutEditMode).toBe(false)
        expect(logic.values.gridLayouts.sm?.[0]).toMatchObject(gridPosition)
    })

    it('saves nothing when the grid only reports the default position of a tile nobody moved', async () => {
        await mountWith({})
        logic.actions.enterLayoutEdit()
        logic.actions.setPendingLayouts({ sm: [{ i: 'tile-1', x: 0, y: 0, w: 6, h: 5 }] })

        expect(logic.values.hasUnsavedLayoutChanges).toBe(false)
        logic.actions.saveLayout()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockedTilePartialUpdate).not.toHaveBeenCalled()
        expect(logic.values.layoutEditMode).toBe(false)
    })
    it('writes the layout once when Save is pressed again while the first save runs', async () => {
        let release: () => void = () => {}
        mockedTilePartialUpdate.mockImplementation(
            (_org, _id, tileId, body) =>
                new Promise((resolve) => {
                    release = () => resolve({ ...TILE, id: tileId, ...body })
                })
        )
        await mountWith({})
        logic.actions.enterLayoutEdit()
        logic.actions.setPendingLayouts(MOVED)

        logic.actions.saveLayout()
        logic.actions.saveLayout()
        expect(logic.values.layoutSaving).toBe(true)
        release()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockedTilePartialUpdate).toHaveBeenCalledTimes(1)
        expect(logic.values.layoutSaving).toBe(false)
    })
})
