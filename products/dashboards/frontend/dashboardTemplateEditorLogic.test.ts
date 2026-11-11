import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { dashboardTemplateEditorLogic } from './dashboardTemplateEditorLogic'

describe('dashboardTemplateEditorLogic', () => {
    let logic: ReturnType<typeof dashboardTemplateEditorLogic.build>
    let getSchema: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        getSchema = jest.spyOn(api.dashboardTemplates, 'getSchema').mockResolvedValue({ type: 'object' })
        logic = dashboardTemplateEditorLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('loads the template schema once, when the editor first opens', async () => {
        expect(getSchema).not.toHaveBeenCalled()

        await expectLogic(logic, () => {
            logic.actions.openDashboardTemplateEditor()
        })
            .toDispatchActions(['getTemplateSchemaSuccess'])
            .toMatchValues({ templateSchema: { type: 'object' } })

        logic.actions.closeDashboardTemplateEditor()
        logic.actions.openDashboardTemplateEditor()

        expect(getSchema).toHaveBeenCalledTimes(1)
    })
})
