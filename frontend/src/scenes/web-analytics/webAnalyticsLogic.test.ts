import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { ProductTab, TileId } from './common'
import { FOCUS_MODE_TILE_IDS } from './focus-mode/focusModeMapping'
import { WebAnalyticsConcern } from './focus-mode/types'
import { webAnalyticsLogic } from './webAnalyticsLogic'

describe('webAnalyticsLogic focus mode', () => {
    let logic: ReturnType<typeof webAnalyticsLogic.build>

    const enableFocusMode = (): void => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WEB_ANALYTICS_FOCUS_MODE], {
            [FEATURE_FLAGS.WEB_ANALYTICS_FOCUS_MODE]: true,
        })
    }

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        jest.spyOn(api.propertyDefinitions, 'list').mockResolvedValue({ results: [] } as any)
        jest.spyOn(api.hogFunctions, 'list').mockResolvedValue({ results: [] } as any)
        featureFlagLogic.mount()
        logic = webAnalyticsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('applies selected concerns by updating hiddenTiles', async () => {
        enableFocusMode()
        logic.actions.openFocusModeModal()
        logic.actions.toggleFocusModeConcern(WebAnalyticsConcern.RETENTION)

        await expectLogic(logic, () => {
            logic.actions.applyFocusMode()
        }).toMatchValues({
            focusModeConcerns: [WebAnalyticsConcern.RETENTION],
            focusModeEnabled: true,
            focusModeModalOpen: false,
            hiddenTiles: FOCUS_MODE_TILE_IDS.filter((tileId) => ![TileId.OVERVIEW, TileId.RETENTION].includes(tileId)),
            isFocusModeActive: true,
        })
    })

    it('does not apply focus mode with an empty selection', async () => {
        enableFocusMode()
        logic.actions.setTileVisibility(TileId.GRAPHS, false)
        logic.actions.openFocusModeModal()

        await expectLogic(logic, () => {
            logic.actions.applyFocusMode()
        }).toMatchValues({
            focusModeConcerns: [],
            focusModeEnabled: false,
            focusModeModalOpen: true,
            hiddenTiles: [TileId.GRAPHS],
            isFocusModeActive: false,
        })
    })

    it('uses saved concerns when reopening focus mode settings', async () => {
        enableFocusMode()
        logic.actions.openFocusModeModal()
        logic.actions.toggleFocusModeConcern(WebAnalyticsConcern.RETENTION)
        logic.actions.applyFocusMode()

        await expectLogic(logic, () => {
            logic.actions.openFocusModeModal()
        }).toMatchValues({
            focusModeDraftConcerns: [WebAnalyticsConcern.RETENTION],
            focusModeModalOpen: true,
        })
    })

    it('exits focus mode without clearing saved concerns', async () => {
        enableFocusMode()
        logic.actions.openFocusModeModal()
        logic.actions.toggleFocusModeConcern(WebAnalyticsConcern.RETENTION)
        logic.actions.applyFocusMode()

        await expectLogic(logic, () => {
            logic.actions.exitFocusMode()
        }).toMatchValues({
            focusModeConcerns: [WebAnalyticsConcern.RETENTION],
            focusModeEnabled: false,
            hiddenTiles: [],
            isFocusModeActive: false,
        })
    })

    it('exits focus mode and preserves manually-hidden non-focus tiles', async () => {
        enableFocusMode()
        logic.actions.setTileVisibility(TileId.WEB_VITALS, false)
        logic.actions.openFocusModeModal()
        logic.actions.toggleFocusModeConcern(WebAnalyticsConcern.RETENTION)
        logic.actions.applyFocusMode()

        await expectLogic(logic, () => {
            logic.actions.exitFocusMode()
        }).toMatchValues({
            focusModeConcerns: [WebAnalyticsConcern.RETENTION],
            focusModeEnabled: false,
            hiddenTiles: [TileId.WEB_VITALS],
            isFocusModeActive: false,
        })
    })

    it('re-enters focus mode using saved concerns', async () => {
        enableFocusMode()
        logic.actions.setFocusModeConcerns([WebAnalyticsConcern.RETENTION])

        await expectLogic(logic, () => {
            logic.actions.enterFocusMode()
        }).toMatchValues({
            focusModeConcerns: [WebAnalyticsConcern.RETENTION],
            focusModeEnabled: true,
            hiddenTiles: FOCUS_MODE_TILE_IDS.filter((tileId) => ![TileId.OVERVIEW, TileId.RETENTION].includes(tileId)),
            isFocusModeActive: true,
        })
    })

    it('resetTileVisibility restores all tiles', async () => {
        logic.actions.setFocusModeEnabled(true)
        logic.actions.setTileVisibility(TileId.GRAPHS, false)

        await expectLogic(logic, () => {
            logic.actions.resetTileVisibility()
        }).toMatchValues({
            focusModeEnabled: false,
            hiddenTiles: [],
        })
    })

    it('hides focus mode when the feature flag is off', async () => {
        await expectLogic(logic).toMatchValues({
            productTab: ProductTab.ANALYTICS,
            showFocusMode: false,
        })
    })
})
