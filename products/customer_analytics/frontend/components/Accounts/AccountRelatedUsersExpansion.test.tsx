import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import api from 'lib/api'
import { OrganizationMembershipLevel } from 'lib/constants'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { userLogic } from 'scenes/userLogic'

import type { HogQLQueryResponse } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import type { UserType } from '~/types'

import { AccountRelatedUsersExpansion } from './AccountRelatedUsersExpansion'

jest.mock('lib/components/TZLabel', () => ({
    TZLabel: ({ time }: { time: string }) => <span>{time}</span>,
}))
jest.mock('lib/utils/copyToClipboard', () => ({
    copyToClipboard: jest.fn().mockResolvedValue(true),
}))

const buildEuRow = (
    userId: number,
    membershipId: string,
    level: OrganizationMembershipLevel,
    firstName: string,
    lastName: string,
    email: string | null,
    distinctId: string,
    lastLogin: string | null
): unknown[] => [userId, membershipId, level, firstName, lastName, email, distinctId, lastLogin]

const ALEX_ROW = buildEuRow(
    42,
    'membership-1',
    OrganizationMembershipLevel.Owner,
    'Alex',
    'Mercer',
    'alex+eu@example.com',
    'distinct-1',
    '2026-01-02T03:04:05Z'
)
const JORDAN_ROW = buildEuRow(
    43,
    'membership-2',
    OrganizationMembershipLevel.Member,
    'Jordan',
    'Bell',
    'jordan+eu@example.com',
    'distinct-2',
    null
)

describe('AccountRelatedUsersExpansion', () => {
    beforeEach(() => {
        initKeaTests()
        jest.restoreAllMocks()
        jest.mocked(copyToClipboard).mockClear()
        userLogic.actions.loadUserSuccess({ is_staff: true } as UserType)
        jest.spyOn(api.organizationMembers, 'listForOrg').mockResolvedValue({
            count: 0,
            next: null,
            previous: null,
            results: [],
        })
        jest.spyOn(api, 'query').mockResolvedValue({ results: [ALEX_ROW, JORDAN_ROW] } as HogQLQueryResponse)
    })

    afterEach(() => {
        cleanup()
    })

    it('shows the EU member access level and opens them in the current admin', async () => {
        render(
            <Provider>
                <AccountRelatedUsersExpansion externalId="organization-1" />
            </Provider>
        )

        expect(await screen.findByText('Owner')).toBeInTheDocument()
        expect(screen.getByText('2026-01-02T03:04:05Z')).toBeInTheDocument()
        expect(screen.getByText('Never')).toBeInTheDocument()
        expect(screen.getByPlaceholderText('Search users by name or email...')).toHaveAttribute('maxLength', '200')
        for (const header of ['Access level', 'Last logged in']) {
            expect(screen.getByText(header).closest('th')).toHaveClass('LemonTable__header--actionable')
        }
        expect(
            screen.getByText('Access level').closest('th')!.querySelector('[data-attr="table-header-more"]')
        ).not.toBeNull()
        const [impersonateButton] = await screen.findAllByText('Impersonate')
        expect(impersonateButton.closest('a')).toHaveAttribute('href', 'http://localhost/admin/posthog/user/42/change/')
    })

    it('copies selected emails across pages and excludes users without an email address', async () => {
        const fillerRows = Array.from({ length: 19 }, (_, index) =>
            buildEuRow(
                100 + index,
                `membership-${index + 3}`,
                OrganizationMembershipLevel.Member,
                `Member${index + 1}`,
                'Example',
                `member${index + 1}@example.com`,
                `distinct-${index + 3}`,
                null
            )
        )
        jest.mocked(api.query).mockResolvedValue({
            results: [
                ALEX_ROW,
                ...fillerRows,
                JORDAN_ROW,
                buildEuRow(
                    44,
                    'membership-without-email',
                    OrganizationMembershipLevel.Member,
                    'Taylor',
                    'Stone',
                    null,
                    'distinct-without-email',
                    null
                ),
            ],
        } as HogQLQueryResponse)

        render(
            <Provider>
                <AccountRelatedUsersExpansion externalId="organization-1" />
            </Provider>
        )

        expect(await screen.findByText('Owner')).toBeInTheDocument()
        fireEvent.click(screen.getByLabelText('Select user Alex Mercer'))
        fireEvent.click(screen.getByLabelText('Next page'))

        expect(await screen.findByText('Jordan Bell')).toBeInTheDocument()
        expect(screen.getByText('1 user selected')).toBeInTheDocument()
        expect(screen.getByLabelText('Select user Taylor Stone')).toBeDisabled()
        fireEvent.click(screen.getByLabelText('Select user Jordan Bell'))

        const copyButton = screen.getByText('Copy email addresses')
        expect(document.querySelector('[data-attr="customer-analytics-account-users-toolbar"]')).toContainElement(
            copyButton
        )
        fireEvent.click(copyButton)

        expect(copyToClipboard).toHaveBeenCalledWith('alex+eu@example.com\njordan+eu@example.com', 'email addresses')
    })
})
