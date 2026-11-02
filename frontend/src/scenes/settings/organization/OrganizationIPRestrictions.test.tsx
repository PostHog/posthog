import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expectLogic } from 'kea-test-utils'

import { billingLogic } from 'lib/logic/billing/billingLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AvailableFeature } from '~/types'

import { OrganizationIPRestrictions } from './OrganizationIPRestrictions'

describe('OrganizationIPRestrictions', () => {
    const organization = {
        ...MOCK_DEFAULT_ORGANIZATION,
        ip_restrictions: ['203.0.113.4'],
        ip_restrictions_enabled: true,
        available_product_features: [{ key: AvailableFeature.IP_RESTRICTIONS, name: 'IP restrictions' }],
    }

    beforeEach(() => {
        initKeaTests(true, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_PROJECT, organization)
        userLogic.mount()
    })

    it('keeps saved rules and blocks another list write while a rejected save is pending', async () => {
        let rejectSave: () => void = () => {}
        const response = new Promise<[number, { detail: string }]>((resolve) => {
            rejectSave = () => resolve([400, { detail: 'Cannot save this list' }])
        })
        useMocks({ patch: { '/api/organizations/:id/': () => response } })
        const logic = organizationLogic()
        render(<OrganizationIPRestrictions />)
        await expectLogic(billingLogic).toFinishAllListeners()
        const input = await screen.findByPlaceholderText('203.0.113.4 or 10.0.0.0/8')
        await waitFor(() => expect(input).not.toBeDisabled())
        await userEvent.type(input, '198.51.100.7')
        expect(input).toHaveValue('198.51.100.7')
        await expectLogic(logic, () => userEvent.click(screen.getByText('Add'))).toDispatchActions([
            'updateOrganization',
        ])

        expect(screen.getByText('203.0.113.4')).toBeInTheDocument()
        expect(screen.queryByText('198.51.100.7')).not.toBeInTheDocument()
        expect(screen.getByText('Add').closest('button')).toHaveAttribute('aria-disabled', 'true')

        await expectLogic(logic, rejectSave).toDispatchActions(['updateOrganizationFailure'])
        await waitFor(() => expect(screen.getByText('Add').closest('button')).toHaveAttribute('aria-disabled', 'false'))
        expect(screen.getByText('203.0.113.4')).toBeInTheDocument()
        expect(screen.queryByText('198.51.100.7')).not.toBeInTheDocument()
    })

    it('allows disabling existing restrictions after entitlement loss', async () => {
        userLogic.actions.loadUserSuccess({
            ...MOCK_DEFAULT_USER,
            organization: { ...organization, available_product_features: [] },
        })
        render(<OrganizationIPRestrictions />)
        const toggle = await screen.findByLabelText('Enable IP restrictions')

        await expectLogic(organizationLogic, () => userEvent.click(toggle)).toDispatchActions([
            organizationLogic.actionCreators.updateOrganization({ ip_restrictions_enabled: false }),
        ])
    })
})
