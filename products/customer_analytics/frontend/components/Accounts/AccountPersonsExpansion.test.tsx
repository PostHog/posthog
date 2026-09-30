import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { initKeaTests } from '~/test/init'

import { accountsPersonsList } from 'products/customer_analytics/frontend/generated/api'
import type {
    AccountPersonApi,
    AccountPersonsResponseApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { AccountPersonsExpansion } from './AccountPersonsExpansion'
import { AccountViewComponent } from './AccountViewComponent'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    ...jest.requireActual('products/customer_analytics/frontend/generated/api'),
    accountsPersonsList: jest.fn(),
}))
jest.mock('lib/components/TZLabel', () => ({
    TZLabel: ({ time }: { time: string }) => <span>{time}</span>,
}))
jest.mock('lib/utils/copyToClipboard', () => ({
    copyToClipboard: jest.fn().mockResolvedValue(true),
}))
jest.mock('../CustomerTasks/CustomerTasksTabContent', () => ({ CustomerTasksTabContent: () => null }))
jest.mock('../EventStream/AccountEventStreamToggle', () => ({ AccountEventStreamToggle: () => null }))
jest.mock('./AccountBillingExpansion', () => ({ AccountBillingExpansion: () => null }))
jest.mock('./AccountConversationsExpansion', () => ({ AccountConversationsExpansion: () => null }))
jest.mock('./AccountFeatureRequestsExpansion', () => ({ AccountFeatureRequestsExpansion: () => null }))
jest.mock('./AccountMeetingsExpansion', () => ({ AccountMeetingsExpansion: () => null }))
jest.mock('./AccountNotesExpansion', () => ({ AccountNotesExpansion: () => null }))
jest.mock('./AccountOpportunitiesExpansion', () => ({ AccountOpportunitiesExpansion: () => null }))
jest.mock('./AccountRelationshipsExpansion', () => ({ AccountRelationshipsExpansion: () => null }))

const mockList = accountsPersonsList as jest.MockedFunction<typeof accountsPersonsList>

const person = (name: string, email: string | null, overrides: Partial<AccountPersonApi> = {}): AccountPersonApi => ({
    id: `id-${name.toLowerCase().replace(/\W/g, '-')}`,
    name,
    distinct_ids: [`distinct-${name}`],
    properties: email === null ? {} : { email },
    account_first_seen: '2025-01-02T03:04:05Z',
    account_last_seen: '2026-01-02T03:04:05Z',
    ...overrides,
})

const pageOf = (results: AccountPersonApi[], hasMore = false): AccountPersonsResponseApi => ({
    results,
    limit: 20,
    offset: 0,
    has_more: hasMore,
})

const ADA = person('Ada Lovelace', 'ada@example.com')
const GRACE = person('Grace Hopper', 'grace@example.com')
const NO_EMAIL = person('Ghost Person', null)

describe('AccountPersonsExpansion', () => {
    beforeEach(() => {
        initKeaTests()
        // Not resetAllMocks: it would also wipe the global ResizeObserver mock that LemonTable's scroll area needs.
        mockList.mockReset()
        jest.mocked(copyToClipboard).mockReset().mockResolvedValue(true)
        mockList.mockResolvedValue(pageOf([ADA, GRACE, NO_EMAIL]))
    })

    afterEach(() => {
        cleanup()
    })

    const renderTab = (): void => {
        render(
            <Provider>
                <AccountPersonsExpansion accountId="account-1" />
            </Provider>
        )
    }

    it('shows each person with email and account activity, linking to their profile', async () => {
        renderTab()

        const link = await screen.findByText('Ada Lovelace')
        expect(link.closest('a')).toHaveAttribute('href', expect.stringContaining(`/persons/${ADA.id}`))
        expect(screen.getByText('ada@example.com')).toBeInTheDocument()
        expect(screen.getAllByText('2025-01-02T03:04:05Z')).toHaveLength(3)
        expect(screen.getAllByText('2026-01-02T03:04:05Z')).toHaveLength(3)
        expect(screen.getByText('No email')).toBeInTheDocument()
        for (const header of ['Email', 'First activity', 'Last activity']) {
            expect(screen.getByText(header).closest('th')).toHaveClass('LemonTable__header--actionable')
        }
        // Access level, last login, and impersonation belong to the organization-members path only.
        expect(screen.queryByText('Access level')).not.toBeInTheDocument()
        expect(screen.queryByText('Last logged in')).not.toBeInTheDocument()
        expect(screen.queryByText('Impersonate')).not.toBeInTheDocument()
    })

    it('shows a placeholder, not a value, for a selected property the API left out', async () => {
        render(
            <Provider>
                <AccountPersonsExpansion accountId="account-1" initialConfig={{ propertyColumns: ['secret_plan'] }} />
            </Provider>
        )

        // The API drops restricted properties from `properties`, and the table must not invent a value.
        await screen.findByText('Ada Lovelace')
        // One label on the removable chip, one on the column header.
        expect(screen.getAllByText('secret_plan')).toHaveLength(2)
        expect(screen.getAllByText('-')).toHaveLength(3)
        expect(mockList).toHaveBeenCalledWith(
            expect.any(String),
            'account-1',
            expect.objectContaining({ select: '["email","secret_plan"]' })
        )
    })

    it('copies selected emails across pages and cannot select a person without an email', async () => {
        mockList.mockResolvedValueOnce(pageOf([ADA, NO_EMAIL], true)).mockResolvedValueOnce(pageOf([GRACE]))
        renderTab()

        await screen.findByText('Ada Lovelace')
        expect(screen.getByLabelText('Select Ghost Person')).toBeDisabled()
        fireEvent.click(screen.getByLabelText('Select Ada Lovelace'))
        fireEvent.click(screen.getByLabelText('Next page'))

        await screen.findByText('Grace Hopper')
        expect(screen.getByText('1 person selected')).toBeInTheDocument()
        fireEvent.click(screen.getByLabelText('Select Grace Hopper'))
        fireEvent.click(screen.getByText('Copy email addresses'))

        await waitFor(() =>
            expect(copyToClipboard).toHaveBeenCalledWith('ada@example.com, grace@example.com', 'email addresses')
        )
        expect(mockList).toHaveBeenLastCalledWith(
            expect.any(String),
            'account-1',
            expect.objectContaining({ offset: 20 })
        )
    })

    it('disables next page on the last page', async () => {
        mockList.mockResolvedValueOnce(pageOf([ADA], true)).mockResolvedValueOnce(pageOf([GRACE], false))
        renderTab()
        await screen.findByText('Ada Lovelace')
        expect(screen.getByLabelText('Next page')).not.toHaveAttribute('aria-disabled', 'true')

        fireEvent.click(screen.getByLabelText('Next page'))

        await screen.findByText('Grace Hopper')
        expect(screen.getByLabelText('Next page')).toHaveAttribute('aria-disabled', 'true')
    })

    it('searches through the API', async () => {
        renderTab()
        await screen.findByText('Ada Lovelace')
        mockList.mockResolvedValue(pageOf([ADA]))

        fireEvent.change(screen.getByPlaceholderText('Search name, email, or ID'), { target: { value: 'ada' } })

        await waitFor(() =>
            expect(mockList).toHaveBeenLastCalledWith(
                expect.any(String),
                'account-1',
                expect.objectContaining({ search: 'ada', offset: 0 })
            )
        )
    })

    describe('states', () => {
        it('shows loading, not the empty message, while the first request is pending', async () => {
            mockList.mockReturnValue(new Promise(() => {}))
            renderTab()

            await waitFor(() => expect(mockList).toHaveBeenCalled())
            expect(document.querySelector('.LemonTable--loading, .LemonTable__loader')).toBeInTheDocument()
            expect(screen.queryByText('No people are associated with this account yet.')).not.toBeInTheDocument()
            expect(screen.queryByText(/Couldn't load people/)).not.toBeInTheDocument()
        })

        it('shows the empty message for an account with no people', async () => {
            mockList.mockResolvedValue(pageOf([]))
            renderTab()

            expect(await screen.findByText('No people are associated with this account yet.')).toBeInTheDocument()
        })

        it('shows the filtered-empty message when a search matches nobody', async () => {
            renderTab()
            await screen.findByText('Ada Lovelace')
            mockList.mockResolvedValue(pageOf([]))

            fireEvent.change(screen.getByPlaceholderText('Search name, email, or ID'), { target: { value: 'nobody' } })

            expect(await screen.findByText(/No people match your search or filters/)).toBeInTheDocument()
            expect(screen.queryByText('No people are associated with this account yet.')).not.toBeInTheDocument()
        })

        it('shows an error with a retry, then the people once the retry succeeds', async () => {
            mockList.mockRejectedValueOnce(new Error('boom'))
            renderTab()

            expect(await screen.findByText(/Couldn't load people/)).toBeInTheDocument()
            expect(screen.queryByText('No people are associated with this account yet.')).not.toBeInTheDocument()

            fireEvent.click(screen.getByText('Try again'))

            expect(await screen.findByText('Ada Lovelace')).toBeInTheDocument()
            expect(screen.queryByText(/Couldn't load people/)).not.toBeInTheDocument()
        })
    })
})

describe('Users tab read source flag', () => {
    beforeEach(() => {
        initKeaTests()
        mockList.mockReset()
        mockList.mockResolvedValue(pageOf([ADA]))
        jest.spyOn(api.organizationMembers, 'listForOrg').mockResolvedValue({
            count: 1,
            next: null,
            previous: null,
            results: [
                {
                    id: 'membership-1',
                    level: 1,
                    user: {
                        id: 1,
                        distinct_id: 'd1',
                        first_name: 'Old',
                        last_name: 'Member',
                        email: 'old@example.com',
                    },
                    last_login: null,
                },
            ],
        } as any)
    })

    afterEach(() => {
        cleanup()
        jest.mocked(api.organizationMembers.listForOrg).mockRestore()
    })

    const renderUsersTab = (): void => {
        render(
            <Provider>
                <AccountViewComponent kind="users" accountId="account-1" externalId="external-1" />
            </Provider>
        )
    }

    it('reads only the persons API when the flag is on', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_PERSONS_UI]: true })
        renderUsersTab()

        expect(await screen.findByText('Ada Lovelace')).toBeInTheDocument()
        expect(mockList).toHaveBeenCalledWith(expect.any(String), 'account-1', expect.anything())
        expect(api.organizationMembers.listForOrg).not.toHaveBeenCalled()
        expect(screen.queryByText('Access level')).not.toBeInTheDocument()
    })

    it('reads only the organization members when the flag is off', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_PERSONS_UI]: false })
        renderUsersTab()

        expect(await screen.findByText('Old Member')).toBeInTheDocument()
        expect(api.organizationMembers.listForOrg).toHaveBeenCalledWith('external-1', expect.anything())
        expect(mockList).not.toHaveBeenCalled()
        expect(screen.getByText('Access level')).toBeInTheDocument()
    })

    it('does not fall back to the other source when the flagged source fails', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_PERSONS_UI]: true })
        mockList.mockRejectedValue(new Error('boom'))
        renderUsersTab()

        expect(await screen.findByText(/Couldn't load people/)).toBeInTheDocument()
        expect(api.organizationMembers.listForOrg).not.toHaveBeenCalled()
    })
})
