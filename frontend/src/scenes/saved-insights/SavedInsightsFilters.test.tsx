import { MOCK_DEFAULT_BASIC_USER, MOCK_SECOND_BASIC_USER } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SavedInsightsFilters } from './SavedInsightsFilters'
import { SavedInsightFilters, cleanFilters } from './savedInsightsLogic'

const DEFAULT_FILTERS: SavedInsightFilters = cleanFilters({})

describe('SavedInsightsFilters Created by dropdown', () => {
    let setFilters: jest.Mock

    beforeEach(() => {
        useMocks({
            get: {
                '/api/organizations/@current/members/': {
                    results: [
                        {
                            id: '1',
                            user: MOCK_DEFAULT_BASIC_USER,
                            level: 8,
                            joined_at: '2020-09-24T15:05:26.758796Z',
                            updated_at: '2020-09-24T15:05:26.758837Z',
                            is_2fa_enabled: false,
                            has_social_auth: false,
                            last_login: '2020-09-24T15:05:26.758796Z',
                        },
                        {
                            id: '2',
                            user: MOCK_SECOND_BASIC_USER,
                            level: 1,
                            joined_at: '2021-03-11T19:11:11Z',
                            updated_at: '2021-03-11T19:11:11Z',
                            is_2fa_enabled: false,
                            has_social_auth: false,
                            last_login: '2021-03-11T19:11:11Z',
                        },
                    ],
                },
            },
        })
        initKeaTests()
        setFilters = jest.fn()
    })

    afterEach(() => {
        cleanup()
    })

    function renderFilters(filters: Partial<SavedInsightFilters> = {}): void {
        render(
            <Provider>
                <SavedInsightsFilters filters={{ ...DEFAULT_FILTERS, ...filters }} setFilters={setFilters} />
            </Provider>
        )
    }

    it('loads and displays members when dropdown opens', async () => {
        renderFilters()
        await userEvent.click(screen.getByText('Created by'))

        await waitFor(() => {
            expect(screen.getByText('John')).toBeInTheDocument()
            expect(screen.getByText('Rose')).toBeInTheDocument()
        })
    })

    it('filters members by search term', async () => {
        renderFilters()
        await userEvent.click(screen.getByText('Created by'))

        await waitFor(() => {
            expect(screen.getByText('John')).toBeInTheDocument()
        })

        const overlay = screen.getByText('John').closest('.max-w-100')!
        const searchInput = within(overlay as HTMLElement).getByPlaceholderText('Search')
        await userEvent.type(searchInput, 'Rose')

        await waitFor(() => {
            expect(screen.getByText('Rose')).toBeInTheDocument()
            expect(screen.queryByText('John')).not.toBeInTheDocument()
        })
    })

    it('shows no matches for unrecognized search', async () => {
        renderFilters()
        await userEvent.click(screen.getByText('Created by'))

        await waitFor(() => {
            expect(screen.getByText('John')).toBeInTheDocument()
        })

        const overlay = screen.getByText('John').closest('.max-w-100')!
        const searchInput = within(overlay as HTMLElement).getByPlaceholderText('Search')
        await userEvent.type(searchInput, 'zzzzz')

        await waitFor(() => {
            expect(screen.getByText('No matches')).toBeInTheDocument()
        })
    })

    it('toggles member selection and calls setFilters', async () => {
        renderFilters()
        await userEvent.click(screen.getByText('Created by'))

        await waitFor(() => {
            expect(screen.getByText('Rose')).toBeInTheDocument()
        })

        await userEvent.click(screen.getByText('Rose'))

        expect(setFilters).toHaveBeenCalledWith({ createdBy: [MOCK_SECOND_BASIC_USER.id] })
    })
})
