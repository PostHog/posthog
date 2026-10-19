import { MOCK_DEFAULT_PROJECT } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { navigation3000Logic } from './navigationLogic'

describe('navigation3000Logic', () => {
    it.each([
        [false, 'full'],
        [true, 'minimal'],
    ])('on my tickets, a project with is_pending_deletion=%s shows %s navigation', async (isPendingDeletion, mode) => {
        initKeaTests()
        router.actions.push(urls.myTickets())
        projectLogic.mount()
        const logic = navigation3000Logic()
        logic.mount()

        projectLogic.actions.loadCurrentProjectSuccess({
            ...MOCK_DEFAULT_PROJECT,
            is_pending_deletion: isPendingDeletion,
        })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.mode).toEqual(mode)
    })
})
