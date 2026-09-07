import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import api from 'lib/api'
import { OrganizationMembershipLevel } from 'lib/constants'
import { userLogic } from 'scenes/userLogic'

import type { HogQLQueryResponse } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import type { UserType } from '~/types'

import { AccountRelatedUsersExpansion } from './AccountRelatedUsersExpansion'

jest.mock('lib/components/TZLabel', () => ({
    TZLabel: ({ time }: { time: string }) => <span>{time}</span>,
}))

describe('AccountRelatedUsersExpansion', () => {
    beforeEach(() => {
        initKeaTests()
        jest.restoreAllMocks()
        userLogic.actions.loadUserSuccess({ is_staff: true } as UserType)
    })

    afterEach(() => {
        cleanup()
    })

    it('shows the EU member access level and opens them in the current admin', async () => {
        jest.spyOn(api.organizationMembers, 'listForOrg').mockResolvedValue({
            count: 0,
            next: null,
            previous: null,
            results: [],
        })
        jest.spyOn(api, 'query').mockResolvedValue({
            results: [
                [
                    42,
                    'membership-1',
                    OrganizationMembershipLevel.Owner,
                    'Alex',
                    'Mercer',
                    'alex+eu@example.com',
                    'distinct-1',
                    '2026-01-02T03:04:05Z',
                ],
                [
                    43,
                    'membership-2',
                    OrganizationMembershipLevel.Member,
                    'Jordan',
                    'Bell',
                    'jordan+eu@example.com',
                    'distinct-2',
                    null,
                ],
            ],
        } as HogQLQueryResponse)

        render(
            <Provider>
                <AccountRelatedUsersExpansion externalId="organization-1" />
            </Provider>
        )

        expect(await screen.findByText('Owner')).toBeInTheDocument()
        expect(screen.getByText('2026-01-02T03:04:05Z')).toBeInTheDocument()
        expect(screen.getByText('Never')).toBeInTheDocument()
        expect(screen.getByPlaceholderText('Search users by name or email...')).toHaveAttribute('maxLength', '200')
        const [impersonateButton] = await screen.findAllByText('Impersonate')
        expect(impersonateButton.closest('a')).toHaveAttribute('href', 'http://localhost/admin/posthog/user/42/change/')
    })
})
