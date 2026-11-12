import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
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
    afterEach(cleanup)

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
        const input = await screen.findByLabelText('Allowed IP addresses and CIDR blocks')
        await waitFor(() => expect(input).not.toBeDisabled())
        await userEvent.type(input, '198.51.100.7{enter}')
        expect(screen.getByText('198.51.100.7')).toBeInTheDocument()
        await expectLogic(logic, () => userEvent.click(screen.getByText('Save'))).toDispatchActions([
            'updateOrganization',
        ])

        expect(screen.getByText('203.0.113.4')).toBeInTheDocument()
        expect(screen.getByText('198.51.100.7')).toBeInTheDocument()
        expect(logic.values.currentOrganization?.ip_restrictions).toEqual(organization.ip_restrictions)
        expect(input).toBeDisabled()
        expect(screen.getByText('Save').closest('button')).toHaveAttribute('aria-disabled', 'true')

        await expectLogic(logic, rejectSave).toDispatchActions(['updateOrganizationFailure'])
        await waitFor(() =>
            expect(screen.getByText('Save').closest('button')).toHaveAttribute('aria-disabled', 'false')
        )
        expect(screen.getByText('203.0.113.4')).toBeInTheDocument()
        expect(screen.getByText('198.51.100.7')).toBeInTheDocument()
        expect(logic.values.currentOrganization?.ip_restrictions).toEqual(organization.ip_restrictions)
    })

    it('edits a saved list while keeping enforcement disabled', async () => {
        const disabled = { ...organization, ip_restrictions_enabled: false }
        const updated = { ...disabled, ip_restrictions: [...disabled.ip_restrictions, '198.51.100.7'] }
        useMocks({ patch: { '/api/organizations/:id/': updated } })
        const logic = organizationLogic()
        render(<OrganizationIPRestrictions />)
        act(() => logic.actions.loadCurrentOrganizationSuccess(disabled))
        await expectLogic(billingLogic).toFinishAllListeners()
        const input = await screen.findByLabelText('Allowed IP addresses and CIDR blocks')
        await waitFor(() => expect(input).not.toBeDisabled())
        expect(screen.getByLabelText('Enable IP restrictions')).not.toBeChecked()
        await userEvent.type(input, '198.51.100.7{enter}')
        await expectLogic(logic, () => userEvent.click(screen.getByText('Save'))).toDispatchActions([
            logic.actionCreators.updateOrganization({
                ip_restrictions: updated.ip_restrictions,
                ip_restrictions_enabled: false,
            }),
            'updateOrganizationSuccess',
        ])
        expect(screen.getByText('198.51.100.7')).toBeInTheDocument()
        expect(screen.getByLabelText('Enable IP restrictions')).not.toBeChecked()
    })

    it.each(['203.0.113.4/32', '2001:db8::4/128'])('rejects CIDR %s in the single-address tester', async (ip) => {
        render(<OrganizationIPRestrictions />)
        const input = await screen.findByPlaceholderText('203.0.113.4')
        await userEvent.type(input, ip)
        expect(screen.getByText('Test').closest('button')).toHaveAttribute('aria-disabled', 'true')
    })

    it.each(['127.1', '192.168.001.001'])('keeps invalid IPv4 draft %s editable without saving it', async (ip) => {
        render(<OrganizationIPRestrictions />)
        await expectLogic(billingLogic).toFinishAllListeners()
        const input = await screen.findByLabelText('Allowed IP addresses and CIDR blocks')
        await waitFor(() => expect(input).not.toBeDisabled())
        await userEvent.type(input, `${ip}{enter}`)
        expect(screen.getByText(ip)).toBeInTheDocument()
        expect(screen.getByText('Save').closest('button')).toHaveAttribute('aria-disabled', 'true')
        expect(
            screen.getByText('Enter a valid IP address or CIDR block, such as 203.0.113.4 or 10.0.0.0/8.')
        ).toBeInTheDocument()
    })

    it('prevents enabling without entitlement when billing has no feature metadata', async () => {
        const disabled = { ...organization, ip_restrictions_enabled: false, available_product_features: [] }
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, organization: disabled })
        render(<OrganizationIPRestrictions />)
        const logic = organizationLogic()
        act(() => logic.actions.loadCurrentOrganizationSuccess(disabled))
        await expectLogic(billingLogic).toFinishAllListeners()
        const toggle = await screen.findByLabelText('Enable IP restrictions')
        const update = jest.spyOn(logic.actions, 'updateOrganization')

        expect(toggle).toBeDisabled()
        await userEvent.click(toggle)
        expect(update).not.toHaveBeenCalled()
        expect(toggle).not.toBeChecked()
        update.mockRestore()
    })

    it('allows disabling existing restrictions after entitlement loss', async () => {
        userLogic.actions.loadUserSuccess({
            ...MOCK_DEFAULT_USER,
            organization: { ...organization, available_product_features: [] },
        })
        render(<OrganizationIPRestrictions />)
        await expectLogic(billingLogic).toFinishAllListeners()
        const toggle = await screen.findByLabelText('Enable IP restrictions')

        await expectLogic(organizationLogic, () => userEvent.click(toggle)).toDispatchActions([
            organizationLogic.actionCreators.updateOrganization({ ip_restrictions_enabled: false }),
        ])
    })
})
