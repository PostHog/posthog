import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { settingsSceneLogic } from './settingsSceneLogic'

describe('settingsSceneLogic', () => {
    let logic: ReturnType<typeof settingsSceneLogic.build>

    beforeEach(async () => {
        initKeaTests()
        logic = settingsSceneLogic()
        logic.mount()
    })

    it('reads filters from the URL', async () => {
        router.actions.push('/settings/project-product-analytics', {}, { 'person-display-name': true })

        await expectLogic(logic).toMatchValues({
            selectedLevel: 'project',
        })

        expect(router.values.hashParams).toEqual({ 'person-display-name': true })
    })
})
