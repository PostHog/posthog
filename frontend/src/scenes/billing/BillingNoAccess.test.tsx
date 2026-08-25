import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { OrganizationMembershipLevel } from 'lib/constants'
import { membersLogic } from 'scenes/organization/membersLogic'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'
import { OrganizationMemberType } from '~/types'

import { BillingNoAccess } from './BillingNoAccess'

const member = (firstName: string, email: string, level: OrganizationMembershipLevel): OrganizationMemberType =>
    ({
        id: email,
        user: { uuid: email, first_name: firstName, last_name: 'Test', email },
        level,
    }) as OrganizationMemberType

describe('<BillingNoAccess />', () => {
    beforeEach(() => {
        initKeaTests()
        userLogic.mount()
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, uuid: 'me@test.com' } as any)
        membersLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    it('points a blocked member at the org admins and owners to ask', () => {
        membersLogic.actions.loadAllMembersSuccess([
            member('Olive', 'owner@test.com', OrganizationMembershipLevel.Owner),
            member('Aiden', 'admin@test.com', OrganizationMembershipLevel.Admin),
            member('Mena', 'member@test.com', OrganizationMembershipLevel.Member),
        ])

        render(<BillingNoAccess reason="You don't have access to billing" />)

        expect(screen.getByText('Olive Test')).toHaveAttribute('href', 'mailto:owner@test.com')
        expect(screen.getByText('Aiden Test')).toHaveAttribute('href', 'mailto:admin@test.com')
        // A plain member cannot change billing, so they are not offered as a contact.
        expect(screen.queryByText('Mena Test')).not.toBeInTheDocument()
    })

    it('omits the contact list when no admins are known', () => {
        membersLogic.actions.loadAllMembersSuccess([
            member('Mena', 'member@test.com', OrganizationMembershipLevel.Member),
        ])

        render(<BillingNoAccess reason="You don't have access to billing" />)

        expect(screen.queryByText('Ask an organization admin to make billing changes:')).not.toBeInTheDocument()
        expect(screen.getByText('Go back home')).toBeInTheDocument()
    })
})
