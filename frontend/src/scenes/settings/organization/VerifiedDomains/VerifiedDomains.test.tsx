import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AvailableFeature } from '~/types'

import { VerifiedDomains } from './VerifiedDomains'
import { verifiedDomainsLogic } from './verifiedDomainsLogic'

const domainsResponse = (jitProvisioningEnabled: boolean): Record<string, unknown> => ({
    count: 1,
    next: null,
    previous: null,
    results: [
        {
            id: '8db3b0c2-a0ab-490a-9037-14f3358a81bc',
            domain: 'my.example.com',
            jit_provisioning_enabled: jitProvisioningEnabled,
            sso_enforcement: '',
            is_verified: true,
            verified_at: '2022-01-01T23:59:59',
        },
    ],
})

describe('<VerifiedDomains />', () => {
    let logic: ReturnType<typeof verifiedDomainsLogic.build>
    let jitProvisioningEnabled: boolean

    beforeEach(() => {
        useMocks({
            get: {
                '/api/organizations/:organization/identity_provider_configs/': {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                },
                '/api/organizations/:organization/domains': () => [200, domainsResponse(jitProvisioningEnabled)],
            },
        })
        // The organization has SSO enforcement but not automatic provisioning, so "Upgrade to enable"
        // can only come from the automatic provisioning column.
        initKeaTests(true, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_PROJECT, {
            ...MOCK_DEFAULT_ORGANIZATION,
            available_product_features: [
                { key: AvailableFeature.SSO_ENFORCEMENT, name: AvailableFeature.SSO_ENFORCEMENT },
            ],
        })
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    const renderTable = async (): Promise<void> => {
        logic = verifiedDomainsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        render(<VerifiedDomains />)
    }

    // Without the feature the API still accepts turning provisioning off, so an admin keeps the switch
    // for a domain that has it on.
    it('keeps the automatic provisioning switch when the unentitled domain has it on', async () => {
        jitProvisioningEnabled = true
        await renderTable()

        expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'true')
        expect(screen.queryByText('Upgrade to enable')).not.toBeInTheDocument()
    })

    it('shows the upgrade link when the unentitled domain has provisioning off', async () => {
        jitProvisioningEnabled = false
        await renderTable()

        expect(screen.getByText('Upgrade to enable')).toBeInTheDocument()
        expect(screen.queryByRole('switch')).not.toBeInTheDocument()
    })
})
