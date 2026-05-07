import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { initKeaTests } from '~/test/init'
import { mockActionDefinition, mockGetEventDefinitions, mockGetPropertyDefinitions } from '~/test/mocks'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { recentTaxonomicFiltersLogic } from '../TaxonomicFilter/recentTaxonomicFiltersLogic'
import { TaxonomicFilterGroupType } from '../TaxonomicFilter/types'
import { PropertyFilters } from './PropertyFilters'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

describe('PropertyFilters recent selections', () => {
    beforeEach(() => {
        initKeaTests()
        actionsModel.mount()
        groupsModel.mount()
        propertyDefinitionsModel.mount()
        localStorage.clear()
        recentTaxonomicFiltersLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    function useSetupMocks(overrides: Record<string, unknown> = {}): void {
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': mockGetEventDefinitions,
                '/api/projects/:team/property_definitions': mockGetPropertyDefinitions,
                '/api/projects/:team/actions': { results: [mockActionDefinition] },
                '/api/environments/:team/persons/properties': [],
                '/api/environments/:team/events/values': {
                    results: [{ name: 'Chrome' }, { name: 'Firefox' }, { name: 'Safari' }],
                    refreshing: false,
                },
                '/api/event/values/': {
                    results: [{ name: 'Chrome' }, { name: 'Firefox' }, { name: 'Safari' }],
                    refreshing: false,
                },
                '/api/environments/:team/persons/values': [{ name: 'alice@example.com' }, { name: 'bob@example.com' }],
                '/api/environments/:team_id/quick_filters/': { results: [] },
                ...overrides,
            },
            post: {
                '/api/environments/:team/query': { results: [] },
            },
        })
    }

    function renderFilters(props: Partial<React.ComponentProps<typeof PropertyFilters>> = {}): { onChange: jest.Mock } {
        const onChange = jest.fn()
        render(
            <Provider>
                <PropertyFilters
                    pageKey="recents-e2e"
                    onChange={onChange}
                    taxonomicGroupTypes={[
                        TaxonomicFilterGroupType.EventProperties,
                        TaxonomicFilterGroupType.PersonProperties,
                    ]}
                    {...props}
                />
            </Provider>
        )
        return { onChange }
    }

    async function openNewFilter(): Promise<void> {
        await userEvent.click(screen.getByTestId('new-prop-filter-recents-e2e'))
        await waitFor(() => {
            expect(screen.getByTestId('taxonomic-filter-searchfield')).toBeInTheDocument()
        })
    }

    async function switchToTab(tabTestId: string): Promise<void> {
        await userEvent.click(screen.getByTestId(tabTestId))
    }

    async function searchFor(query: string): Promise<void> {
        await userEvent.type(screen.getByTestId('taxonomic-filter-searchfield'), query)
    }

    async function selectItem(itemTestId: string, onChange: jest.Mock): Promise<void> {
        await userEvent.click(screen.getByTestId(itemTestId))
        await waitFor(() => {
            expect(onChange).toHaveBeenCalled()
        })
    }

    async function pickShortcutItem({
        tabTestId,
        searchQuery,
        itemTestId,
        onChange,
    }: {
        tabTestId: string
        searchQuery: string
        itemTestId: string
        onChange: jest.Mock
    }): Promise<void> {
        await openNewFilter()
        await switchToTab(tabTestId)
        await searchFor(searchQuery)
        await waitFor(() => {
            expect(screen.getByTestId(itemTestId)).toBeInTheDocument()
        })
        await selectItem(itemTestId, onChange)
    }

    async function pickPropertyWithValue({
        propertySearch,
        propertyItemTestId,
        value,
        onChange,
    }: {
        propertySearch: string
        propertyItemTestId: string
        value: string
        onChange: jest.Mock
    }): Promise<void> {
        await openNewFilter()
        await switchToTab('taxonomic-tab-event_properties')
        await searchFor(propertySearch)
        await waitFor(() => {
            const item = screen.getByTestId(propertyItemTestId)
            expect(item).toBeInTheDocument()
            expect(item.textContent).toMatch(/browser/i)
        })
        await userEvent.click(screen.getByTestId(propertyItemTestId))
        await waitFor(() => {
            expect(onChange).toHaveBeenCalled()
        })

        const valueInput = await screen.findByPlaceholderText('Enter value...')
        await userEvent.type(valueInput, value)
        await waitFor(() => {
            expect(screen.getByTestId('prop-val-0')).toBeInTheDocument()
        })
        await userEvent.click(screen.getByTestId('prop-val-0'))
    }

    function expectRecentInSuggestedFilters(index: number, pattern: RegExp): void {
        expect(screen.getByTestId(`prop-filter-suggested_filters-${index}`)).toHaveTextContent(pattern)
    }

    function expectRecentCount(count: number): void {
        expect(recentTaxonomicFiltersLogic.values.recentFilters).toHaveLength(count)
    }

    it.each([
        {
            description: 'pageview URL',
            taxonomicGroupTypes: [TaxonomicFilterGroupType.PageviewUrls, TaxonomicFilterGroupType.EventProperties],
            mockOverrides: {
                '/api/environments/:team/events/values': [
                    { name: 'https://example.com/pricing' },
                    { name: 'https://example.com/blog' },
                ],
            },
            tabTestId: 'taxonomic-tab-pageview_urls',
            searchQuery: 'example',
            itemTestId: 'prop-filter-pageview_urls-0',
            expectedRecentPattern: /Current URL.*∋.*example\.com\/pricing/i,
        },
        {
            description: 'screen name',
            taxonomicGroupTypes: [TaxonomicFilterGroupType.Screens, TaxonomicFilterGroupType.EventProperties],
            mockOverrides: {
                '/api/environments/:team/events/values': [{ name: 'HomeScreen' }, { name: 'SettingsScreen' }],
            },
            tabTestId: 'taxonomic-tab-screens',
            searchQuery: 'Home',
            itemTestId: 'prop-filter-screens-0',
            expectedRecentPattern: /Screen Name.*=.*HomeScreen/i,
        },
        {
            description: 'email address',
            taxonomicGroupTypes: [TaxonomicFilterGroupType.EmailAddresses, TaxonomicFilterGroupType.PersonProperties],
            mockOverrides: {
                '/api/environments/:team/persons/values': [{ name: 'alice@example.com' }, { name: 'bob@example.com' }],
            },
            tabTestId: 'taxonomic-tab-email_addresses',
            searchQuery: 'alice',
            itemTestId: 'prop-filter-email_addresses-0',
            expectedRecentPattern: /email.*=.*alice@example\.com/i,
        },
    ])(
        'shortcut group: selecting a $description records and displays it in recents',
        async ({ taxonomicGroupTypes, mockOverrides, tabTestId, searchQuery, itemTestId, expectedRecentPattern }) => {
            useSetupMocks(mockOverrides)
            const { onChange } = renderFilters({ taxonomicGroupTypes })

            await pickShortcutItem({ tabTestId, searchQuery, itemTestId, onChange })

            await waitFor(() => {
                expectRecentCount(1)
                expect(recentTaxonomicFiltersLogic.values.recentFilters[0].propertyFilter).toBeTruthy()
            })

            await openNewFilter()

            await waitFor(() => {
                expectRecentInSuggestedFilters(0, expectedRecentPattern)
            })
        }
    )

    it('selecting a property and completing the value records to recents', async () => {
        useSetupMocks()
        const { onChange } = renderFilters({ sendAllKeyUpdates: true })

        await pickPropertyWithValue({
            propertySearch: '$browser',
            propertyItemTestId: 'prop-filter-event_properties-0',
            value: 'Chrome',
            onChange,
        })

        await waitFor(() => {
            expectRecentCount(1)
            const recent = recentTaxonomicFiltersLogic.values.recentFilters[0]
            expect(recent.propertyFilter).toBeTruthy()
            expect(recent.propertyFilter?.key).toBe('$browser')
            expect([recent.propertyFilter?.value].flat()).toContain('Chrome')
        })

        await openNewFilter()

        await waitFor(() => {
            expectRecentInSuggestedFilters(0, /Browser.*=.*Chrome/i)
        })
    })

    it('recents show at top of suggested filters before search', async () => {
        useSetupMocks({
            '/api/environments/:team/events/values': [
                { name: 'https://example.com/first' },
                { name: 'https://example.com/second' },
            ],
        })
        const { onChange } = renderFilters({
            taxonomicGroupTypes: [TaxonomicFilterGroupType.PageviewUrls, TaxonomicFilterGroupType.EventProperties],
        })

        await pickShortcutItem({
            tabTestId: 'taxonomic-tab-pageview_urls',
            searchQuery: 'first',
            itemTestId: 'prop-filter-pageview_urls-0',
            onChange,
        })

        await waitFor(() => {
            expectRecentCount(1)
        })

        await openNewFilter()

        await waitFor(() => {
            expectRecentInSuggestedFilters(0, /Current URL.*∋.*example\.com\/first/i)
        })
    })

    it('search hint shows alongside recents', async () => {
        useSetupMocks({
            '/api/environments/:team/events/values': [{ name: 'https://example.com/pricing' }],
        })
        const { onChange } = renderFilters({
            taxonomicGroupTypes: [TaxonomicFilterGroupType.PageviewUrls, TaxonomicFilterGroupType.EventProperties],
        })

        await pickShortcutItem({
            tabTestId: 'taxonomic-tab-pageview_urls',
            searchQuery: 'pricing',
            itemTestId: 'prop-filter-pageview_urls-0',
            onChange,
        })

        await waitFor(() => {
            expectRecentCount(1)
        })

        await openNewFilter()

        await waitFor(() => {
            expect(screen.getByTestId('prop-filter-suggested_filters-0')).toBeInTheDocument()
            expect(screen.getByText(/Start searching/)).toBeInTheDocument()
        })
    })

    it('recents prefix disappears when searching', async () => {
        useSetupMocks({
            '/api/environments/:team/events/values': [{ name: 'https://example.com/pricing' }],
        })
        const { onChange } = renderFilters({
            taxonomicGroupTypes: [TaxonomicFilterGroupType.PageviewUrls, TaxonomicFilterGroupType.EventProperties],
        })

        await pickShortcutItem({
            tabTestId: 'taxonomic-tab-pageview_urls',
            searchQuery: 'pricing',
            itemTestId: 'prop-filter-pageview_urls-0',
            onChange,
        })

        await waitFor(() => {
            expectRecentCount(1)
        })

        await openNewFilter()

        await waitFor(() => {
            expect(screen.getByTestId('prop-filter-suggested_filters-0')).toBeInTheDocument()
        })

        await searchFor('zzzznonexistent')

        await waitFor(() => {
            expect(screen.queryByTestId('prop-filter-suggested_filters-0')).not.toBeInTheDocument()
        })
    })

    it('recents from unavailable groups are hidden', async () => {
        useSetupMocks()

        recentTaxonomicFiltersLogic.actions.recordRecentFilter({
            groupType: TaxonomicFilterGroupType.PersonProperties,
            groupName: 'Person properties',
            value: 'location',
            item: { name: 'location' },
            propertyFilter: {
                key: 'location',
                type: PropertyFilterType.Person,
                value: 'US',
                operator: PropertyOperator.Exact,
            },
        })

        expectRecentCount(1)

        renderFilters({
            taxonomicGroupTypes: [TaxonomicFilterGroupType.EventProperties],
        })

        await openNewFilter()

        await waitFor(() => {
            expect(screen.queryByTestId('prop-filter-suggested_filters-0')).not.toBeInTheDocument()
        })
    })

    it('multiple selections limited to 3 in suggested filters', async () => {
        const groupTypes = [TaxonomicFilterGroupType.PageviewUrls, TaxonomicFilterGroupType.EventProperties]

        const searches = ['a.com', 'b.com', 'c.com', 'd.com']
        for (const query of searches) {
            cleanup()
            useSetupMocks({
                '/api/environments/:team/events/values': [{ name: `https://${query}/page` }],
            })
            const { onChange } = renderFilters({ taxonomicGroupTypes: groupTypes })

            await pickShortcutItem({
                tabTestId: 'taxonomic-tab-pageview_urls',
                searchQuery: query,
                itemTestId: 'prop-filter-pageview_urls-0',
                onChange,
            })

            await waitFor(() => {
                expect(recentTaxonomicFiltersLogic.values.recentFilters.length).toBeGreaterThanOrEqual(
                    searches.indexOf(query) + 1
                )
            })
        }

        expectRecentCount(4)

        cleanup()
        useSetupMocks()
        renderFilters({ taxonomicGroupTypes: groupTypes })
        await openNewFilter()

        await waitFor(() => {
            expect(screen.getByTestId('prop-filter-suggested_filters-0')).toBeInTheDocument()
            expect(screen.getByTestId('prop-filter-suggested_filters-1')).toBeInTheDocument()
            expect(screen.getByTestId('prop-filter-suggested_filters-2')).toBeInTheDocument()
        })
        expect(screen.queryByTestId('prop-filter-suggested_filters-3')).not.toBeInTheDocument()
    }, 15000)

    it('searching in recents matches by property filter value', async () => {
        useSetupMocks({
            '/api/environments/:team/events/values': [{ name: 'https://example.com/pricing' }],
        })
        const { onChange } = renderFilters({
            taxonomicGroupTypes: [TaxonomicFilterGroupType.PageviewUrls, TaxonomicFilterGroupType.EventProperties],
        })

        await pickShortcutItem({
            tabTestId: 'taxonomic-tab-pageview_urls',
            searchQuery: 'pricing',
            itemTestId: 'prop-filter-pageview_urls-0',
            onChange,
        })

        await waitFor(() => {
            expectRecentCount(1)
        })

        await openNewFilter()

        await switchToTab('taxonomic-tab-recent_filters')

        await searchFor('pricing')

        await waitFor(() => {
            expect(screen.getByTestId('prop-filter-recent_filters-0')).toBeInTheDocument()
            expect(screen.getByTestId('prop-filter-recent_filters-0')).toHaveTextContent(/pricing/i)
        })
    })

    describe('category dropdown inside property modal', () => {
        let unmountFeatureFlagLogic: (() => void) | null = null

        beforeEach(() => {
            unmountFeatureFlagLogic = featureFlagLogic.mount()
        })

        afterEach(() => {
            featureFlagLogic.actions.setFeatureFlags([], {})
            unmountFeatureFlagLogic?.()
            unmountFeatureFlagLogic = null
        })

        it('pill variant: clicking the inline category trigger does not close the property modal', async () => {
            useSetupMocks()
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TAXONOMIC_FILTER_CATEGORY_DROPDOWN], {
                [FEATURE_FLAGS.TAXONOMIC_FILTER_CATEGORY_DROPDOWN]: 'pill',
            })

            renderFilters({
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                ],
            })

            await openNewFilter()

            const trigger = await screen.findByTestId('taxonomic-category-dropdown-trigger-pill')
            await userEvent.click(trigger)

            expect(screen.getByTestId('taxonomic-filter-searchfield')).toBeInTheDocument()
        })

        it('pill variant: picking a category in the inline dropdown does not close the property modal', async () => {
            useSetupMocks()
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TAXONOMIC_FILTER_CATEGORY_DROPDOWN], {
                [FEATURE_FLAGS.TAXONOMIC_FILTER_CATEGORY_DROPDOWN]: 'pill',
            })

            renderFilters({
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                ],
            })

            await openNewFilter()

            const trigger = await screen.findByTestId('taxonomic-category-dropdown-trigger-pill')
            await userEvent.click(trigger)

            const item = await screen.findByTestId('taxonomic-category-dropdown-item-person_properties')
            await userEvent.click(item)

            expect(screen.getByTestId('taxonomic-filter-searchfield')).toBeInTheDocument()
        })

        it('control: clicking outside the property modal closes it', async () => {
            useSetupMocks()
            renderFilters({
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                ],
            })

            await openNewFilter()

            expect(screen.getByTestId('taxonomic-filter-searchfield')).toBeInTheDocument()

            await userEvent.click(document.body)

            await waitFor(() => {
                expect(screen.queryByTestId('taxonomic-filter-searchfield')).not.toBeInTheDocument()
            })
        })
    })
})
