import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { initKeaTests } from '~/test/init'

import { agentSetupModalLogic } from './agentSetupModalLogic'

describe('agentSetupModalLogic', () => {
    let logic: ReturnType<typeof agentSetupModalLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('restores the GitHub modal from the callback URL and only removes GitHub parameters when closed', () => {
        router.actions.push('/inbox/config', {
            setup: 'github',
            integration_id: '12',
            installation_id: '34',
            github_setup_error: 'pending',
            error_message: 'Try again',
            github_install_pending: '1',
            source: 'saved-filter',
        })
        const callbackPath = router.values.location.pathname

        logic = agentSetupModalLogic()
        logic.mount()

        expect(logic.values.openModal).toBe('github')

        logic.actions.closeSetupModal()

        expect(router.values.location.pathname).toBe(callbackPath)
        expect(router.values.searchParams).toEqual({ source: 'saved-filter' })
    })

    it('revalidates the shared integrations cache when the GitHub modal opens', async () => {
        logic = agentSetupModalLogic()
        logic.mount()

        // Opening the modal (manually or via the post-redirect URL reopen) must reload the shared
        // list so a connection made outside this tab's lifetime isn't shown as missing.
        await expectLogic(logic, () => {
            logic.actions.openSetupModal('github')
        }).toDispatchActions([integrationsLogic.actionTypes.loadIntegrations])
    })

    it('revalidates the shared integrations cache when the GitHub modal closes', async () => {
        router.actions.push('/inbox/config', { setup: 'github' })
        logic = agentSetupModalLogic()
        logic.mount()

        // The shared list is loaded once on app mount and never refreshed; closing the GitHub
        // modal must reload it so a connection made during the round-trip isn't shown as missing.
        await expectLogic(logic, () => {
            logic.actions.closeSetupModal()
        }).toDispatchActions([integrationsLogic.actionTypes.loadIntegrations])
    })
})
