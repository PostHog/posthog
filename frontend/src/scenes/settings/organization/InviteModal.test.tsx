import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AvailableFeature, OrganizationType } from '~/types'

import { organizationLogic } from '../../organizationLogic'
import { userLogic } from '../../userLogic'
import { inviteLogic } from './inviteLogic'
import { InviteRow } from './InviteModal'

jest.mock('./GuestResourcePicker', () => ({
    GuestResourcePicker: () => null,
}))

function mountWithOwnerAndAccessControl(): void {
    const organization: Partial<OrganizationType> = {
        id: 'org-1',
        name: 'Test',
        slug: 'test',
        membership_level: 15, // Owner — can assign Member/Admin/Owner
        available_product_features: [{ key: AvailableFeature.ACCESS_CONTROL, name: 'Access control' }] as any,
        teams: [] as any,
        member_count: 1,
        metadata: {} as any,
    }
    organizationLogic.mount()
    organizationLogic.actions.loadCurrentOrganizationSuccess(organization as OrganizationType)
    userLogic.mount()
    userLogic.actions.loadUserSuccess({
        organization,
        uuid: 'u',
        email: 'admin@posthog.com',
        first_name: 'Admin',
        organizations: [organization],
    } as any)
    featureFlagLogic.mount()
    featureFlagLogic.actions.setFeatureFlags(['guest-mode'], { 'guest-mode': true })
    inviteLogic.mount()
}

function queryLevelDropdown(): HTMLElement | null {
    return document.querySelector('[data-attr="invite-row-org-member-level"]')
}

async function openLevelDropdown(): Promise<void> {
    const select = queryLevelDropdown()
    if (!select) {
        throw new Error('level dropdown not rendered')
    }
    await userEvent.click(select)
}

function renderRow(): void {
    render(<InviteRow index={0} isDeletable={false} />)
}

describe('InviteRow — Guest option in org-level dropdown', () => {
    beforeEach(() => {
        useMocks({
            get: {
                'api/users/@me/': () => [200, { organization: {} }],
            },
        })
        initKeaTests()
    })

    it('Guest option is present and ordered first, with Member as the default', async () => {
        mountWithOwnerAndAccessControl()
        renderRow()
        await openLevelDropdown()

        const menuitems = await screen.findAllByRole('menuitem')
        const labels = menuitems.map((el) => el.textContent)
        expect(labels).toEqual(['Guest', 'Member', 'Admin', 'Owner'])
        // The select button (closed) shows Member as the default.
        expect(queryLevelDropdown()?.textContent).toContain('Member')
    })

    it('Selecting Guest flips isGuestInvite on the form logic', async () => {
        mountWithOwnerAndAccessControl()
        renderRow()
        await openLevelDropdown()

        const menuitems = await screen.findAllByRole('menuitem')
        const guestItem = menuitems.find((el) => el.textContent === 'Guest')!
        await userEvent.click(guestItem)

        await waitFor(() => {
            expect(inviteLogic.values.isGuestInvite).toBe(true)
        })
    })
})
