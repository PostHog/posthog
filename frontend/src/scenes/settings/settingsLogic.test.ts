import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { organizationIntegrationsLogic } from './organization/organizationIntegrationsLogic'
import { settingsLogic } from './settingsLogic'

describe('settingsLogic', () => {
    let logic: ReturnType<typeof settingsLogic.build>
    let integrationsLogic: ReturnType<typeof organizationIntegrationsLogic.build>

    beforeEach(() => {
        initKeaTests()
        integrationsLogic = organizationIntegrationsLogic()
        integrationsLogic.mount()
        logic = settingsLogic({ logicKey: 'test', sectionId: 'organization-integrations' })
        logic.mount()
    })

    it('keeps the organization-integrations section resolvable once the last integration is disconnected', async () => {
        // Disconnecting the last integration reloads the list down to empty, which previously
        // dropped the section the user was standing on entirely, turning a successful disconnect
        // into a false "setting not found".
        integrationsLogic.actions.loadOrganizationIntegrationsSuccess([])

        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.selectedSection?.id).toBe('organization-integrations')
        expect(logic.values.settings.length).toBeGreaterThan(0)

        // Still hidden from the sidebar nav when there's nothing connected.
        const section = logic.values.sections.find((s) => s.id === 'organization-integrations')
        expect(section?.hideFromNavigation).toBe(true)
    })
})
