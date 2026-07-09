import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import type { SourceConfig } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { availableSourcesLogic } from '../availableSourcesLogic'
import { ALL_SOURCES_CATEGORY, type SourceCategoryFilter, sourceCatalogLogic } from '../sourceCatalogLogic'

const AVAILABLE_SOURCES: Record<string, SourceConfig> = {
    Stripe: {
        name: 'Stripe',
        iconPath: '',
        caption: '',
        fields: [],
    } as unknown as SourceConfig,
    // `Apple` sorts alphabetically first but is unreleased, so connectable-first ordering must
    // still push it below the two available sources.
    Zebra: { name: 'Zebra', label: 'Zebra', fields: [] } as unknown as SourceConfig,
    Mango: { name: 'Mango', label: 'Mango', fields: [] } as unknown as SourceConfig,
    Apple: { name: 'Apple', label: 'Apple', unreleasedSource: true, fields: [] } as unknown as SourceConfig,
}

describe('sourceCatalogLogic', () => {
    let unmountAvailableSources: () => void
    let unmountLogic: () => void

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/external_data_sources/wizard/': AVAILABLE_SOURCES,
            },
        })
        initKeaTests()
        unmountAvailableSources = availableSourcesLogic.mount()
        availableSourcesLogic.actions.loadSuccess(AVAILABLE_SOURCES)
        unmountLogic = sourceCatalogLogic().mount()
    })

    afterEach(() => {
        unmountLogic()
        unmountAvailableSources()
    })

    it.each([
        { search: '  Podium  ', expectedText: 'Podium' },
        { search: '', expectedText: '' },
    ])('seeds the source request text from "$search"', ({ search, expectedText }) => {
        const logic = sourceCatalogLogic()
        if (search) {
            logic.actions.setSearch(search)
        }
        logic.actions.showSourceRequest()

        expect(logic.values.sourceRequestModalOpen).toBe(true)
        expect(logic.values.sourceRequestText).toEqual(expectedText)
    })

    it('browses connectable sources before "Coming soon" ones', () => {
        const logic = sourceCatalogLogic()
        const items = logic.values.filteredItems

        const firstComingSoon = items.findIndex((item) => item.status === 'coming_soon')
        expect(firstComingSoon).toBeGreaterThan(-1)
        // No connectable source may appear after the first "Coming soon" one.
        expect(items.slice(firstComingSoon).every((item) => item.status === 'coming_soon')).toBe(true)

        // `Apple` sorts first alphabetically but, being unreleased, must land after `Mango`/`Zebra`.
        const names = items.map((item) => item.name)
        expect(names.indexOf('Mango')).toBeLessThan(names.indexOf('Apple'))
        expect(names.indexOf('Zebra')).toBeLessThan(names.indexOf('Apple'))
    })

    it('clears the request text when the modal is closed', () => {
        const logic = sourceCatalogLogic()
        logic.actions.setSearch('Podium')
        logic.actions.showSourceRequest()
        logic.actions.hideSourceRequest()

        expect(logic.values.sourceRequestModalOpen).toBe(false)
        expect(logic.values.sourceRequestText).toEqual('')
    })

    it('keeps catalogItems and the search index stable across unrelated feature flag refreshes', () => {
        // featureFlags is a broad dependency that changes identity on every flag load; without
        // result equality that re-derived the whole catalog, rebuilt the Fuse index, and handed
        // every tile a fresh item object per refresh.
        const logic = sourceCatalogLogic()
        featureFlagLogic.mount()
        const initialItems = logic.values.catalogItems
        const initialFuse = logic.values.catalogFuse
        expect(initialItems.length).toBeGreaterThan(0)

        featureFlagLogic.actions.setFeatureFlags(['some-unrelated-flag'], { 'some-unrelated-flag': true })

        expect(logic.values.catalogItems).toBe(initialItems)
        expect(logic.values.catalogFuse).toBe(initialFuse)
    })

    describe('popular sources section', () => {
        const RANKED_SOURCES: Record<string, SourceConfig> = {
            Stripe: {
                name: 'Stripe',
                label: 'Stripe',
                fields: [],
                category: 'Payments & billing',
                popularityRank: 2,
            } as unknown as SourceConfig,
            Postgres: {
                name: 'Postgres',
                label: 'Postgres',
                fields: [],
                category: 'Databases',
                popularityRank: 1,
            } as unknown as SourceConfig,
            Hubspot: { name: 'Hubspot', label: 'Hubspot', fields: [], category: 'CRM' } as unknown as SourceConfig,
        }

        beforeEach(() => {
            availableSourcesLogic.actions.loadSuccess(RANKED_SOURCES)
        })

        it('returns only ranked items, sorted ascending by rank', () => {
            const logic = sourceCatalogLogic()
            expect(logic.values.popularItems.map((item) => item.name)).toEqual(['Postgres', 'Stripe'])
        })

        const showPopularSectionCases: { search: string; category: SourceCategoryFilter; expected: boolean }[] = [
            { search: '', category: ALL_SOURCES_CATEGORY, expected: true },
            { search: 'anything', category: ALL_SOURCES_CATEGORY, expected: false },
            { search: '', category: 'CRM', expected: false },
        ]

        it.each(showPopularSectionCases)(
            'shows the popular section only on the default view (search=$search, category=$category)',
            ({ search, category, expected }) => {
                const logic = sourceCatalogLogic()
                logic.actions.setSearch(search)
                logic.actions.setSelectedCategory(category)
                expect(logic.values.showPopularSection).toBe(expected)
            }
        )

        it('does not show the popular section when nothing is ranked', () => {
            availableSourcesLogic.actions.loadSuccess(AVAILABLE_SOURCES)
            const logic = sourceCatalogLogic()
            expect(logic.values.showPopularSection).toBe(false)
        })

        it('excludes a popular item from the default grid, but includes it once its category is selected', () => {
            const logic = sourceCatalogLogic()
            expect(logic.values.filteredItems.map((item) => item.name)).not.toContain('Stripe')

            logic.actions.setSelectedCategory('Payments & billing')
            expect(logic.values.filteredItems.map((item) => item.name)).toContain('Stripe')
        })

        it('excludes a popular item from the default grid, but includes it once searched by name', () => {
            const logic = sourceCatalogLogic()
            expect(logic.values.filteredItems.map((item) => item.name)).not.toContain('Stripe')

            logic.actions.setSearch('Stripe')
            expect(logic.values.filteredItems.map((item) => item.name)).toContain('Stripe')
        })
    })
})
