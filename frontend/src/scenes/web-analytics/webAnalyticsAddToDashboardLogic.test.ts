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

    // Regression: a click on a second tile used to start a second save, and whichever response
    // landed last rebound the already open picker to the other tile's insight.
    it('ignores a click on another tile while a save is in flight', async () => {
        let resolveCreate: (insight: unknown) => void = () => {}
        createSpy.mockImplementation(
            () =>
                new Promise((resolve) => {
                    resolveCreate = resolve
                })
        )

        logic.actions.addTileToDashboard(TileId.PATHS, 'PATH')
        await expectLogic(logic).toDispatchActions(['saveTileAsInsight'])
        expect(logic.values.savedInsightLoading).toBe(true)

        await expectLogic(logic, () => {
            logic.actions.addTileToDashboard(TileId.SOURCES, 'CHANNEL')
        }).toNotHaveDispatchedActions(['saveTileAsInsight'])

        resolveCreate({ id: 1, short_id: 'abc123', name: 'saved', query: {} })
        await expectLogic(logic)
            .toDispatchActions(['saveTileAsInsightSuccess', 'openAddToDashboardModal'])
            .toMatchValues({ savingTileKey: null, isAddToDashboardModalOpen: true })

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

    // Regression: the bot tables are web table queries that only read as a table inside web
    // analytics, so saving one put a JSON dump on the dashboard instead of a table.
    it('does not offer a tile whose query cannot become an insight query', async () => {
        const crawlers = logic.values.combinedTiles.find((tile) => tile.tileId === TileId.BOT_CRAWLERS)
        expect(crawlers?.kind === 'query' && crawlers.query.kind).toBe(NodeKind.DataTableNode)

        expect(logic.values.canAddTileToDashboard(TileId.PATHS, 'PATH')).toBe(true)
        expect(logic.values.canAddTileToDashboard(TileId.BOT_CRAWLERS)).toBe(false)

        await expectLogic(logic, () => {
            logic.actions.addTileToDashboard(TileId.BOT_CRAWLERS)
        }).toNotHaveDispatchedActions(['saveTileAsInsight'])

        expect(createSpy).not.toHaveBeenCalled()
    })

    it('does nothing for a tile that carries no query', async () => {
        await expectLogic(logic, () => {
            logic.actions.addTileToDashboard(TileId.REPLAY)
        }).toNotHaveDispatchedActions(['saveTileAsInsight'])

        expect(createSpy).not.toHaveBeenCalled()
    })
})
