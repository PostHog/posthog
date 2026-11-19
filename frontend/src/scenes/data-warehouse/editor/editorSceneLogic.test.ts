import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { editorSceneLogic } from './editorSceneLogic'
import { sqlEditorLogic } from './sqlEditorLogic'
import { SQLEditorMode } from './sqlEditorModes'

const TAB_ID = 'editor-scene-test'

describe('editorSceneLogic', () => {
    beforeEach(() => {
        localStorage.clear()
        sessionStorage.clear()
        useMocks({
            get: {
                '/api/projects/:team_id/warehouse_saved_queries/': { results: [] },
                '/api/projects/:team_id/external_data_sources/connections/': [],
                '/api/user_home_settings/@me/': {},
            },
            post: {
                '/api/environments/:team_id/query/': [200, { tables: {}, joins: [] }],
            },
        })
        initKeaTests()
        panelLayoutLogic.mount()
    })

    // Regression: the collapse must end with the flow, or the nav stays collapsed on the next
    // scene. An embedded editor sits inside another scene and must not collapse that scene's nav.
    it.each([
        ['collapses the app nav for the create view flow in the full scene', undefined, true],
        ['leaves the app nav alone in an embedded editor', SQLEditorMode.Embedded, false],
    ])('%s', (_name, mode, collapsedInFlow) => {
        const props = { tabId: TAB_ID, ...(mode ? { mode } : {}) }
        const logic = editorSceneLogic(props)
        logic.mount()
        expect(panelLayoutLogic.values.isLayoutNavCollapsed).toBe(false)

        sqlEditorLogic(props).actions.setEditorSource('view')
        expect(panelLayoutLogic.values.isLayoutNavCollapsed).toBe(collapsedInFlow)

        logic.unmount()
        expect(panelLayoutLogic.values.isLayoutNavCollapsed).toBe(false)
    })
})
