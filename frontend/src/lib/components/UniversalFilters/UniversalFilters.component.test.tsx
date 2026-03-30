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
import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { recentTaxonomicFiltersLogic } from '../TaxonomicFilter/recentTaxonomicFiltersLogic'
import { TaxonomicFilterGroupType } from '../TaxonomicFilter/types'
import UniversalFilters from './UniversalFilters'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

describe('UniversalFilters recent selections', () => {
    beforeEach(() => {
        initKeaTests()
        actionsModel.mount()
        groupsModel.mount()
        propertyDefinitionsModel.mount()
        localStorage.clear()
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.TAXONOMIC_FILTER_RECENTS]: true,
        })
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
                '/api/environments/:team/events/values': [],
                '/api/environments/:team/persons/values': [],
                ...overrides,
            },
            post: {
                '/api/environments/:team/query': { results: [] },
            },
        })
    }

    const DEFAULT_GROUP: UniversalFiltersGroup = {
        type: FilterLogicalOperator.And,
        values: [{ type: FilterLogicalOperator.And, values: [] }],
    }

    function renderUniversalFilters(
        taxonomicGroupTypes: TaxonomicFilterGroupType[],
        onChange?: jest.Mock
    ): { onChange: jest.Mock } {
        const onChangeMock = onChange ?? jest.fn()
        render(
            <Provider>
                <UniversalFilters
                    rootKey="recents-e2e"
                    group={DEFAULT_GROUP}
                    onChange={onChangeMock}
                    taxonomicGroupTypes={taxonomicGroupTypes}
                >
                    <UniversalFilters.AddFilterButton />
                </UniversalFilters>
            </Provider>
        )
        return { onChange: onChangeMock }
    }

    async function openAddFilter(): Promise<void> {
        await userEvent.click(screen.getByText('Add filter'))
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

    async function pickShortcutItem(tabTestId: string, searchQuery: string, itemTestId: string): Promise<void> {
        await openAddFilter()
        await switchToTab(tabTestId)
        await searchFor(searchQuery)
        await waitFor(() => {
            expect(screen.getByTestId(itemTestId)).toBeInTheDocument()
        })
        await userEvent.click(screen.getByTestId(itemTestId))
    }

    function expectRecentCount(count: number): void {
        expect(recentTaxonomicFiltersLogic.values.recentFilters).toHaveLength(count)
    }

    it.each([
        {
            description: 'pageview URL',
            taxonomicGroupTypes: [TaxonomicFilterGroupType.PageviewUrls, TaxonomicFilterGroupType.EventProperties],
            mockOverrides: {
                '/api/environments/:team/events/values': [{ name: 'https://example.com/pricing' }],
            },
            tabTestId: 'taxonomic-tab-pageview_urls',
            searchQuery: 'example',
            itemTestId: 'prop-filter-pageview_urls-0',
            expectedKey: '$current_url',
        },
        {
            description: 'screen name',
            taxonomicGroupTypes: [TaxonomicFilterGroupType.Screens, TaxonomicFilterGroupType.EventProperties],
            mockOverrides: {
                '/api/environments/:team/events/values': [{ name: 'HomeScreen' }],
            },
            tabTestId: 'taxonomic-tab-screens',
            searchQuery: 'Home',
            itemTestId: 'prop-filter-screens-0',
            expectedKey: '$screen_name',
        },
        {
            description: 'email address',
            taxonomicGroupTypes: [TaxonomicFilterGroupType.EmailAddresses, TaxonomicFilterGroupType.PersonProperties],
            mockOverrides: {
                '/api/environments/:team/persons/values': [{ name: 'alice@example.com' }],
            },
            tabTestId: 'taxonomic-tab-email_addresses',
            searchQuery: 'alice',
            itemTestId: 'prop-filter-email_addresses-0',
            expectedKey: 'email',
        },
    ])(
        'selecting a $description records a complete property filter to recents',
        async ({ taxonomicGroupTypes, mockOverrides, tabTestId, searchQuery, itemTestId, expectedKey }) => {
            useSetupMocks(mockOverrides)
            renderUniversalFilters(taxonomicGroupTypes)

            await pickShortcutItem(tabTestId, searchQuery, itemTestId)

            await waitFor(() => {
                expectRecentCount(1)
                const recent = recentTaxonomicFiltersLogic.values.recentFilters[0]
                expect(recent.propertyFilter).toBeTruthy()
                expect(recent.propertyFilter?.key).toBe(expectedKey)
            })
        }
    )
})
