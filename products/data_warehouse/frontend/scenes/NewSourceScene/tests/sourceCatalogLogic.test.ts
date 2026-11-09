import { router } from 'kea-router'

import { PaginatedResponse } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { ExternalDataSource } from '~/types'

import type { SourceConfigResponseApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { sourcesDataLogic } from '../../../shared/logics/sourcesDataLogic'
import { availableSourcesLogic } from '../availableSourcesLogic'
import { sourceCatalogLogic } from '../sourceCatalogLogic'

const AVAILABLE_SOURCES: Record<string, SourceConfigResponseApi> = {
    // Featured, so it must lead the browse list even though `Stripe` sorts after `Mango`.
    Stripe: {
        name: 'Stripe',
        iconPath: '',
        caption: '',
        featured: true,
        fields: [],
    } as unknown as SourceConfigResponseApi,
    // `Apple` sorts alphabetically first but is unreleased, so connectable-first ordering must
    // still push it below the two available sources.
    Zebra: { name: 'Zebra', label: 'Zebra', fields: [] } as unknown as SourceConfigResponseApi,
    Mango: { name: 'Mango', label: 'Mango', fields: [] } as unknown as SourceConfigResponseApi,
    Apple: { name: 'Apple', label: 'Apple', unreleasedSource: true, fields: [] } as unknown as SourceConfigResponseApi,
    // Connectable, and shares the "apple" token with the unreleased `Apple` above so a search for
    // "apple" fuzzy-matches both — used to assert connectable results outrank "Coming soon" ones.
    ApplePay: { name: 'ApplePay', label: 'Apple Pay', fields: [] } as unknown as SourceConfigResponseApi,
    // A Databases-category source, so a search for the words people use for the category itself
    // has something to find.
    Postgres: {
        name: 'Postgres',
        label: 'Postgres',
        category: 'Databases',
        fields: [],
    } as unknown as SourceConfigResponseApi,
    // Two sources in distinct categories, used to assert that a category-filtered search which only
    // matches a source in another category flags a cross-category hint instead of dead-ending.
    Salesforce: {
        name: 'Salesforce',
        label: 'Salesforce',
        category: 'Sales',
        fields: [],
    } as unknown as SourceConfigResponseApi,
    Datadog: {
        name: 'Datadog',
        label: 'Datadog',
        category: 'Engineering & monitoring',
        fields: [],
    } as unknown as SourceConfigResponseApi,
    // An unreleased duplicate of a connector that already works.
    BingAds: {
        name: 'BingAds',
        label: 'Bing Ads',
        keywords: ['microsoft advertising'],
        fields: [],
    } as unknown as SourceConfigResponseApi,
    MicrosoftAdvertising: {
        name: 'MicrosoftAdvertising',
        label: 'Microsoft Advertising (Bing Ads)',
        unreleasedSource: true,
        fields: [],
    } as unknown as SourceConfigResponseApi,
    // Bucket sources, so a search for a file format or a bucket provider has something to find.
    AmazonS3: {
        name: 'AmazonS3',
        label: 'Amazon S3',
        keywords: ['amazon', 'aws', 's3', 'bucket', 'csv', 'parquet'],
        fields: [],
    } as unknown as SourceConfigResponseApi,
    GoogleCloudStorage: {
        name: 'GoogleCloudStorage',
        label: 'Google Cloud Storage',
        keywords: ['gcs', 'gcp', 'bucket', 'csv', 'parquet'],
        fields: [],
    } as unknown as SourceConfigResponseApi,
}

const CONNECTED_SOURCES = {
    results: [{ id: 'abc', source_type: 'Stripe' }],
    count: 1,
    next: null,
    previous: null,
} as unknown as PaginatedResponse<ExternalDataSource>

describe('sourceCatalogLogic', () => {
    let unmountAvailableSources: () => void
    let unmountLogic: () => void

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/external_data_sources/wizard/': AVAILABLE_SOURCES,
                '/api/environments/:team_id/external_data_sources/': CONNECTED_SOURCES,
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

    it('leads the browse list with featured sources', () => {
        const logic = sourceCatalogLogic()
        const names = logic.values.filteredItems.map((item) => item.name)

        // `Stripe` is featured, so it must come before the plain connectable sources even though
        // it sorts after `Mango` alphabetically.
        expect(names.indexOf('Stripe')).toBeLessThan(names.indexOf('Mango'))
        expect(names.indexOf('Stripe')).toBeLessThan(names.indexOf('Zebra'))
    })

    it('ranks connectable search matches above "Coming soon" ones', () => {
        const logic = sourceCatalogLogic()
        logic.actions.setSearch('apple')

        // Both `Apple` (unreleased → "Coming soon") and `Apple Pay` (connectable) match, but a
        // search must never lead with a tile the user can't act on.
        const names = logic.values.filteredItems.map((item) => item.name)
        expect(names).toContain('ApplePay')
        expect(names).toContain('Apple')
        expect(names.indexOf('ApplePay')).toBeLessThan(names.indexOf('Apple'))
    })

    // Each of these dead-ended on "no sources match" and pushed the user to request a source we
    // already have.
    it.each(['csv', 'parquet'])('surfaces the bucket sources when searching for "%s"', (search) => {
        const logic = sourceCatalogLogic()
        logic.actions.setSearch(search)

        expect(logic.values.filteredItems.map((item) => item.name)).toContain('AmazonS3')
    })

    // Fuse matches the whole search term as one pattern, so one extra word buries a term that
    // matches on its own: each of these returned nothing at all, which sent the user to "request
    // a source" for connectors we already have.
    it.each(['parquet file storage', 'amazon s3 bucket'])(
        'retries a multi-word search word by word for "%s"',
        (search) => {
            const logic = sourceCatalogLogic()
            logic.actions.setSearch(search)

            expect(logic.values.filteredItems.length).toBeGreaterThan(0)
        }
    )

    it('ranks a multi-word retry by how many words each source matches', () => {
        const logic = sourceCatalogLogic()
        logic.actions.setSearch('amazon gcs gcp')

        // `GoogleCloudStorage` matches "gcs" and "gcp"; `AmazonS3` only "amazon". The closer match must
        // lead, even though the first word found `AmazonS3` and word order alone would keep it first.
        const names = logic.values.filteredItems.map((item) => item.name)
        expect(names).toContain('AmazonS3')
        expect(names.indexOf('GoogleCloudStorage')).toBeLessThan(names.indexOf('AmazonS3'))
    })

    // "database" already found these through the category name. The word in the product's own
    // name found nothing at all, which sent the user to "request a source".
    it.each(['warehouse', 'dwh'])('finds database sources when searching "%s"', (search) => {
        const logic = sourceCatalogLogic()
        logic.actions.setSearch(search)

        expect(logic.values.filteredItems.map((item) => item.name)).toContain('Postgres')
    })

    it('flags a cross-category match when a category search only hits another category', () => {
        const logic = sourceCatalogLogic()
        logic.actions.setSelectedCategory('Sales')
        logic.actions.setSearch('Datadog')

        // The category filter hides the only match, so the list dead-ends...
        expect(logic.values.filteredItems).toHaveLength(0)
        // ...but the hint knows the source exists in another category and can point the user there.
        expect(logic.values.hasCrossCategoryMatches).toBe(true)

        // The same search across all categories finds it, so the hint is no longer needed.
        logic.actions.setSelectedCategory('all')
        expect(logic.values.filteredItems.map((item) => item.name)).toContain('Datadog')
        expect(logic.values.hasCrossCategoryMatches).toBe(false)
    })

    it.each([
        { flagEnabled: true, expectedOffer: 'Custom' },
        { flagEnabled: false, expectedOffer: null },
    ])(
        'offers the Custom REST source for an unmatched search only when it is connectable ($flagEnabled)',
        ({ flagEnabled, expectedOffer }) => {
            availableSourcesLogic.actions.loadSuccess({
                ...AVAILABLE_SOURCES,
                Custom: {
                    name: 'Custom',
                    label: 'Custom REST source',
                    featureFlag: 'dwh_custom_source',
                    fields: [],
                } as unknown as SourceConfigResponseApi,
            })
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags(flagEnabled ? ['dwh_custom_source'] : [], {
                dwh_custom_source: flagEnabled,
            })
            const logic = sourceCatalogLogic()
            logic.actions.setSearch('qwxzv')

            expect(logic.values.filteredItems).toHaveLength(0)
            // Pointing at a "Coming soon" tile would send the user to a source they can't connect.
            expect(logic.values.customSourceItem?.name ?? null).toEqual(expectedOffer)
        }
    )

    it('opens on the category a link names', () => {
        const logic = sourceCatalogLogic()
        expect(logic.values.selectedCategory).toEqual('all')

        router.actions.push(urls.dataPipelinesNew('source'), { category: 'Databases' })
        expect(logic.values.selectedCategory).toEqual('Databases')

        // An unknown value, such as the old `self-managed` link, leaves the catalog as it is rather than
        // filtering it down to nothing.
        router.actions.push(urls.dataPipelinesNew('source'), { category: 'self-managed' })
        expect(logic.values.selectedCategory).toEqual('Databases')
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

    it.each([
        { search: 'webhook', name: 'event-webhook', previewEnabled: true, expectedMatches: 1 },
        { search: 'webhook', name: 'event-webhook', previewEnabled: false, expectedMatches: 0 },
        { search: 'pixel', name: 'event-tracking-pixel', previewEnabled: true, expectedMatches: 1 },
        { search: 'pixel', name: 'event-tracking-pixel', previewEnabled: false, expectedMatches: 0 },
    ])(
        'shows $name in a "$search" search when the preview is $previewEnabled',
        ({ search, name, previewEnabled, expectedMatches }) => {
            const logic = sourceCatalogLogic()
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags(previewEnabled ? [FEATURE_FLAGS.CDP_HOG_SOURCES] : [], {
                [FEATURE_FLAGS.CDP_HOG_SOURCES]: previewEnabled,
            })

            logic.actions.setSearch(search)

            expect(logic.values.filteredItems.filter((item) => item.name === name)).toHaveLength(expectedMatches)
        }
    )

    it('offers BingAds and not a "Coming soon" duplicate for "microsoft advertising"', () => {
        const logic = sourceCatalogLogic()
        logic.actions.setSearch('microsoft advertising')

        const names = logic.values.filteredItems.map((item) => item.name)
        expect(names).toContain('BingAds')
        expect(names).not.toContain('MicrosoftAdvertising')
    })

    it('flags the source types the project already has', () => {
        const logic = sourceCatalogLogic()
        sourcesDataLogic.actions.loadSourcesSuccess(CONNECTED_SOURCES)

        // Stripe is already connected, so its tile has to say so before the user works through
        // the whole flow only to be told a table prefix is needed.
        const byName = Object.fromEntries(logic.values.catalogItems.map((item) => [item.name, item]))
        expect(byName.Stripe.existingSource).toBe(true)
        expect(byName.Mango.existingSource).toBeUndefined()
    })

    it('records which "Coming soon" sources the visit already asked about', () => {
        const logic = sourceCatalogLogic()
        const apple = logic.values.catalogItems.find((item) => item.name === 'Apple')!

        logic.actions.registerInterest(apple)
        logic.actions.registerInterest(apple)

        // The tile swaps to a confirmation once it is in here, so a second entry would let the
        // same source be registered twice.
        expect(logic.values.registeredInterestSources).toEqual(['Apple'])
    })

    it('leaves the incoming webhook source out of a catalog restricted to warehouse sources', () => {
        const logic = sourceCatalogLogic({ allowedSources: ['Stripe'] })
        const unmountRestricted = logic.mount()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.CDP_HOG_SOURCES], {
            [FEATURE_FLAGS.CDP_HOG_SOURCES]: true,
        })

        expect(logic.values.catalogItems.some((item) => item.name.startsWith('event-'))).toBe(false)

        unmountRestricted()
    })
})
