import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import api from 'lib/api'
import { OrganizationMembershipLevel } from 'lib/constants'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import type { HogQLQueryResponse } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import type { OrganizationMemberType, UserType } from '~/types'

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

    it.each([
        { probeStatus: 200, currentUser: { id: 1, is_impersonated: false }, shouldNavigate: false },
        { probeStatus: 503, currentUser: {}, shouldNavigate: true },
        { probeStatus: 200, currentUser: undefined, shouldNavigate: true },
        { probeStatus: 200, currentUser: null, shouldNavigate: true },
        { probeStatus: 200, currentUser: {}, shouldNavigate: true },
    ])(
        'handles identity $probeStatus/$currentUser after confirming impersonation',
        async ({ probeStatus, currentUser, shouldNavigate }) => {
            jest.mocked(api.organizationMembers.listForOrg).mockResolvedValue({
                count: 2,
                next: null,
                previous: null,
                results: [
                    {
                        id: 'membership-1',
                        level: OrganizationMembershipLevel.Owner,
                        last_login: '2026-01-02T03:04:05Z',
                        user: { id: 42, first_name: 'Alex', last_name: 'Mercer', email: 'alex@example.com' },
                    },
                    {
                        id: 'membership-2',
                        level: OrganizationMembershipLevel.Member,
                        last_login: null,
                        user: { id: 43, first_name: 'Jordan', last_name: 'Bell', email: 'jordan@example.com' },
                    },
                ] as OrganizationMemberType[],
            })
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
            expect(impersonateButton.closest('a')).toBeNull()
            fireEvent.click(impersonateButton)
            expect(await screen.findByText('Log in as Alex Mercer')).toBeInTheDocument()
            expect(screen.getByLabelText('Read-only mode (recommended)')).toBeChecked()

            useMocks({
                get: {
                    '/admin/auth_check': () => [200, {}],
                    '/api/users/@me/': () => (currentUser === undefined ? [probeStatus] : [probeStatus, currentUser]),
                },
                post: {
                    '/admin/login/user/42/': () => [200, { success: true }],
                },
            })
            const originalLocation = window.location
            const assign = jest.fn()
            Object.defineProperty(window, 'location', {
                configurable: true,
                value: { ...originalLocation, assign },
            })

            try {
                fireEvent.change(screen.getByLabelText('Reason'), {
                    target: { value: 'Investigate a support request' },
                })
                const logInButton = screen.getByText('Log in', { selector: 'button span' }).closest('button')!
                fireEvent.click(logInButton)
                expect(logInButton).toHaveAttribute('aria-disabled', 'true')
                if (shouldNavigate) {
                    await waitFor(() => expect(assign).toHaveBeenCalledWith('/'))
                    expect(logInButton).toHaveAttribute('aria-disabled', 'true')
                    expect(screen.getByText('Cancel').closest('button')).toHaveAttribute('aria-disabled', 'true')
                    fireEvent.click(screen.getByText('Cancel'))
                } else {
                    await waitFor(() => expect(logInButton).toHaveAttribute('aria-disabled', 'false'))
                    expect(assign).not.toHaveBeenCalled()
                }
                expect(screen.getByText('Log in as Alex Mercer')).toBeInTheDocument()
            } finally {
                Object.defineProperty(window, 'location', { configurable: true, value: originalLocation })
            }
        }
    )

    it.each(['https://eu.posthog.com', 'https://us.posthog.com', 'http://localhost:8000'])(
        'sends warehouse members through the admin identity form on %s',
        async (origin) => {
            const originalLocation = window.location
            Object.defineProperty(window, 'location', {
                configurable: true,
                value: { ...originalLocation, origin },
            })
            try {
                render(
                    <Provider>
                        <AccountRelatedUsersExpansion externalId="organization-1" />
                    </Provider>
                )
                const [button] = await screen.findAllByText('Impersonate')
                const adminOrigin = origin.includes('posthog.com') ? 'https://eu.posthog.com' : origin
                expect(button.closest('a')).toHaveAttribute(
                    'href',
                    `${adminOrigin}/admin/console/users/42/log-in-as/log-in/`
                )
                expect(screen.queryByText('Log in as Alex Mercer')).not.toBeInTheDocument()
            } finally {
                Object.defineProperty(window, 'location', { configurable: true, value: originalLocation })
            }
        }
    )

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
