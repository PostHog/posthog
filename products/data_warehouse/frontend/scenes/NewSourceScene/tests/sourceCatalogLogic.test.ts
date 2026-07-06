import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import type { SourceConfig } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { availableSourcesLogic } from '../availableSourcesLogic'
import { sourceCatalogLogic } from '../sourceCatalogLogic'

const AVAILABLE_SOURCES: Record<string, SourceConfig> = {
    Stripe: {
        name: 'Stripe',
        iconPath: '',
        caption: '',
        fields: [],
    } as unknown as SourceConfig,
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
})
