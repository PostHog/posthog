import { userPreferencesLogic } from 'lib/logic/userPreferencesLogic'

import { initKeaTests } from '~/test/init'

import { eventPropertyFilteringLogic } from './eventPropertyFilteringLogic'

describe('eventPropertyFilteringLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('hides core properties without a $ prefix when PostHog properties are hidden', () => {
        const logic = eventPropertyFilteringLogic()
        logic.mount()
        userPreferencesLogic.actions.setHidePostHogPropertiesInTable(true)

        expect(logic.values.filterProperties({ $browser: 'Chrome', title: 'Pricing', plan: 'pro' })).toEqual({
            plan: 'pro',
        })
    })
})
