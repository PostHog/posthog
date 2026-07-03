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
})
