import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { TileId } from './common'
import { webAnalyticsAddToDashboardLogic } from './webAnalyticsAddToDashboardLogic'
import { webAnalyticsLogic } from './webAnalyticsLogic'
import { webAnalyticsModalLogic } from './webAnalyticsModalLogic'

describe('webAnalyticsAddToDashboardLogic', () => {
    let logic: ReturnType<typeof webAnalyticsAddToDashboardLogic.build>
    let createSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api.propertyDefinitions, 'list').mockResolvedValue({ results: [] } as any)
        jest.spyOn(api.hogFunctions, 'list').mockResolvedValue({ results: [] } as any)
        jest.spyOn(api, 'update').mockResolvedValue({} as any)
        createSpy = jest
            .spyOn(api.insights, 'create')
            .mockResolvedValue({ id: 1, short_id: 'abc123', name: 'saved', query: {} } as any)
        featureFlagLogic.mount()
        webAnalyticsLogic().mount()
        webAnalyticsModalLogic().mount()
        logic = webAnalyticsAddToDashboardLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('saves the tile as an insight named after the tile, then opens the picker', async () => {
        await expectLogic(logic, () => {
            logic.actions.addTileToDashboard(TileId.PATHS, 'PATH')
        })
            .toDispatchActions(['saveTileAsInsight'])
            .toMatchValues({ savingTileKey: 'PATHS.PATH' })
            .toDispatchActions(['saveTileAsInsightSuccess', 'openAddToDashboardModal'])
            .toMatchValues({ isAddToDashboardModalOpen: true, savingTileKey: null })

        expect(createSpy).toHaveBeenCalledTimes(1)
        const created = createSpy.mock.calls[0][0]
        expect(created.saved).toBe(true)
        expect(created.name).toMatch(/^Web analytics: /)
        // Tiles hold table and raw web queries; a dashboard tile needs an insight query.
        expect(created.query.kind).toBe(NodeKind.InsightVizNode)
    })

    // Regression: re-clicking the button used to be the only way back to the picker, so an
    // unchanged tile would save a fresh duplicate insight on every click.
    it('reuses the saved insight while the tile query is unchanged', async () => {
        logic.actions.addTileToDashboard(TileId.PATHS, 'PATH')
        await expectLogic(logic).toDispatchActions(['saveTileAsInsightSuccess'])
        logic.actions.closeAddToDashboardModal()

        await expectLogic(logic, () => {
            logic.actions.addTileToDashboard(TileId.PATHS, 'PATH')
        })
            .toDispatchActions(['openAddToDashboardModal'])
            .toNotHaveDispatchedActions(['saveTileAsInsight'])
            .toMatchValues({ isAddToDashboardModalOpen: true })

        expect(createSpy).toHaveBeenCalledTimes(1)
    })

    it('keeps the picker closed when the save fails', async () => {
        createSpy.mockRejectedValue(new Error('nope'))

        await expectLogic(logic, () => {
            logic.actions.addTileToDashboard(TileId.PATHS, 'PATH')
        })
            .toDispatchActions(['saveTileAsInsightFailure'])
            .toNotHaveDispatchedActions(['openAddToDashboardModal'])
            .toMatchValues({ isAddToDashboardModalOpen: false, savingTileKey: null })
    })

    it('does nothing for a tile that carries no query', async () => {
        await expectLogic(logic, () => {
            logic.actions.addTileToDashboard(TileId.REPLAY)
        }).toNotHaveDispatchedActions(['saveTileAsInsight'])

        expect(createSpy).not.toHaveBeenCalled()
    })
})
