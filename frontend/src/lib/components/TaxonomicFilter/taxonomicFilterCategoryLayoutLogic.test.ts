import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { taxonomicFilterCategoryLayoutLogic } from './taxonomicFilterCategoryLayoutLogic'

jest.mock('posthog-js', () => ({
    __esModule: true,
    default: { capture: jest.fn() },
}))

describe('taxonomicFilterCategoryLayoutLogic', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    it('sets the category rail preference and captures its new value', () => {
        const logic = taxonomicFilterCategoryLayoutLogic.build()
        logic.mount()

        expectLogic(logic, () => {
            logic.actions.setCategoryRailPinned(true)
        })
            .toDispatchActions(['setCategoryRailPinned'])
            .toMatchValues({ categoryRailPinned: true })

        expect(posthog.capture).toHaveBeenCalledWith('taxonomic filter category rail toggled', { docked: true })

        logic.unmount()
    })
})
