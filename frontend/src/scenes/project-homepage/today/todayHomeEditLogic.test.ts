import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { todayHomeEditLogic } from './todayHomeEditLogic'

describe('todayHomeEditLogic', () => {
    it.each([
        { name: 'leaving Home ends edit mode', path: urls.dashboards(), editing: false },
        { name: 'a URL change within Home keeps edit mode', path: `${urls.projectHomepage()}?tab=1`, editing: true },
    ])('$name', ({ path, editing }) => {
        initKeaTests()
        router.actions.push(urls.projectHomepage())
        const logic = todayHomeEditLogic()
        logic.mount()

        logic.actions.toggleHomeEditing()
        router.actions.push(path)

        expect(logic.values.homeEditing).toBe(editing)
    })
})
