import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'

import { __clearTaxonomicResourceCache } from '../hooks/useTaxonomicResource'
import { TaxonomicFilterGroupType } from '../types'
import { TaxonomicFilterHeadless } from './index'

jest.mock('~/queries/query', () => ({
    performQuery: jest.fn(),
}))

jest.mock('lib/api', () => ({
    __esModule: true,
    default: {
        get: jest.fn(),
    },
}))

const apiGet = jest.requireMock('lib/api').default.get as jest.MockedFunction<any>

describe('TaxonomicFilterHeadless integration', () => {
    let onChangeMock: jest.Mock
    let user: ReturnType<typeof userEvent.setup>

    beforeEach(() => {
        __clearTaxonomicResourceCache()
        apiGet.mockReset()
        ;(performQuery as jest.Mock).mockResolvedValue({ tables: {}, joins: [] })
        useMocks({
            get: { '/api/projects/:team/event_definitions': { results: [], count: 0 } },
            post: { '/api/environments/:team/query': { results: [] } },
        })
        initKeaTests()
        actionsModel.mount()
        groupsModel.mount()
        onChangeMock = jest.fn()
        user = userEvent.setup()
    })

    afterEach(() => cleanup())

    function renderHeadless(): void {
        render(
            <Provider>
                <TaxonomicFilterHeadless.Root
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Wildcards]}
                    onChange={onChangeMock}
                    optionsFromProp={{
                        [TaxonomicFilterGroupType.Wildcards]: [{ name: 'wildcard-a' }, { name: 'wildcard-b' }],
                    }}
                >
                    <TaxonomicFilterHeadless.Input />
                    <TaxonomicFilterHeadless.Categories />
                    <TaxonomicFilterHeadless.Panel
                        emptyState={<div data-attr="empty">No results</div>}
                        loadingState={<div data-attr="loading">Loading…</div>}
                    />
                </TaxonomicFilterHeadless.Root>
            </Provider>
        )
    }

    it('mounts Root, Input, Categories and Panel without throwing', () => {
        apiGet.mockResolvedValue({ results: [{ id: 1, name: 'pageview' }], count: 1 })
        renderHeadless()
        expect(screen.getByTestId('taxonomic-filter-searchfield')).toBeInTheDocument()
        expect(screen.getByTestId('taxonomic-tab-events')).toBeInTheDocument()
        expect(screen.getByTestId('taxonomic-tab-wildcard')).toBeInTheDocument()
    })

    it("renders the active tab's items in the Panel", async () => {
        apiGet.mockResolvedValue({
            results: [
                { id: 1, name: 'pageview' },
                { id: 2, name: 'click' },
            ],
            count: 2,
        })
        renderHeadless()
        // Events group prepends a static "All events" option, then remote results follow.
        await waitFor(() => expect(screen.getByText('pageview')).toBeInTheDocument())
        expect(screen.getByText('click')).toBeInTheDocument()
    })

    it('typing in the Input filters via the search query', async () => {
        apiGet.mockImplementation((url: string) => {
            if (url.includes('search=click')) {
                return Promise.resolve({ results: [{ id: 2, name: 'click' }], count: 1 })
            }
            return Promise.resolve({
                results: [
                    { id: 1, name: 'pageview' },
                    { id: 2, name: 'click' },
                ],
                count: 2,
            })
        })
        renderHeadless()
        await waitFor(() => expect(screen.getByText('pageview')).toBeInTheDocument())
        await user.type(screen.getByTestId('taxonomic-filter-searchfield'), 'click')
        await waitFor(() => expect(screen.queryByText('pageview')).not.toBeInTheDocument())
        expect(screen.getByText('click')).toBeInTheDocument()
    })

    it('clicking a row fires onChange', async () => {
        const item = { id: 7, name: 'pageview' }
        apiGet.mockResolvedValue({ results: [item], count: 1 })
        renderHeadless()
        await waitFor(() => screen.getByText('pageview'))
        await user.click(screen.getByText('pageview'))
        expect(onChangeMock).toHaveBeenCalledWith(
            expect.objectContaining({ type: TaxonomicFilterGroupType.Events }),
            'pageview',
            item
        )
    })

    it("switching tabs renders the other tab's items", async () => {
        apiGet.mockResolvedValue({ results: [], count: 0 })
        renderHeadless()
        await user.click(screen.getByTestId('taxonomic-tab-wildcard'))
        await waitFor(() => expect(screen.getByText('wildcard-a')).toBeInTheDocument())
        expect(screen.getByText('wildcard-b')).toBeInTheDocument()
    })

    it('Enter selects the highlighted row', async () => {
        const item = { id: 1, name: 'pageview' }
        apiGet.mockResolvedValue({ results: [item], count: 1 })
        renderHeadless()
        await waitFor(() => screen.getByText('pageview'))
        const input = screen.getByTestId('taxonomic-filter-searchfield')
        ;(input as HTMLInputElement).focus()
        // Hovering 'pageview' bumps the registered list's index to its row.
        // userEvent.hover dispatches mouseenter, which our Panel routes into
        // useGroupList.setIndex.
        await user.hover(screen.getByText('pageview'))
        await user.keyboard('{Enter}')
        expect(onChangeMock).toHaveBeenCalledWith(
            expect.objectContaining({ type: TaxonomicFilterGroupType.Events }),
            'pageview',
            item
        )
    })

    it('shows the empty-state slot when local search returns nothing', async () => {
        apiGet.mockResolvedValue({ results: [], count: 0 })
        renderHeadless()
        await user.click(screen.getByTestId('taxonomic-tab-wildcard'))
        await user.type(screen.getByTestId('taxonomic-filter-searchfield'), 'no-match-zzz')
        await waitFor(() => expect(screen.getByTestId('empty')).toBeInTheDocument())
    })
})
