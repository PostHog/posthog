import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { conversationsWidgetSavedViewsLogic } from './conversationsWidgetSavedViewsLogic'

describe('conversationsWidgetSavedViewsLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('caches an empty saved-view result for the project', async () => {
        const logic = conversationsWidgetSavedViewsLogic({ projectId: 2 })
        logic.mount()

        await expectLogic(logic, () => logic.actions.loadSavedViewsSuccess([])).toMatchValues({
            savedViews: [],
            savedViewsLoaded: true,
        })

        logic.unmount()
    })
})
