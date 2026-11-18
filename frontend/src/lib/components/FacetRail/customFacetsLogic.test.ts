import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import {
    userFacetSettingsPartialUpdate,
    userFacetSettingsRetrieve,
} from 'products/platform_features/frontend/generated/api'
import {
    UserFacetSettingsEntrySourceTypeEnumApi,
    UserFacetSettingsRetrieveProduct,
} from 'products/platform_features/frontend/generated/api.schemas'

import { CustomFacetsProduct, customFacetsLogic } from './customFacetsLogic'

jest.mock('products/platform_features/frontend/generated/api', () => ({
    __esModule: true,
    userFacetSettingsRetrieve: jest.fn(),
    userFacetSettingsPartialUpdate: jest.fn(),
}))

const mockRetrieve = userFacetSettingsRetrieve as jest.MockedFunction<typeof userFacetSettingsRetrieve>
const mockPartialUpdate = userFacetSettingsPartialUpdate as jest.MockedFunction<typeof userFacetSettingsPartialUpdate>

const ATTRIBUTE = UserFacetSettingsEntrySourceTypeEnumApi.Attribute
const RESOURCE_ATTRIBUTE = UserFacetSettingsEntrySourceTypeEnumApi.ResourceAttribute

describe('customFacetsLogic', () => {
    // Each test sets up its mocks, then mounts fresh via `mount()` below. Mounting inside
    // `beforeEach` would fire `afterMount` before a test's own mock override took effect, since
    // re-calling the wrapper mid-test returns the same already-mounted instance.
    let mounted: ReturnType<typeof customFacetsLogic.build>[] = []

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.CUSTOM_FACET_PINNING]: true })
        mockRetrieve.mockResolvedValue({ custom_facets: [] })
        mockPartialUpdate.mockImplementation(async (_uuid, _params, body) => ({
            custom_facets: body?.custom_facets ?? [],
        }))
    })

    afterEach(() => {
        mounted.forEach((logic) => logic.unmount())
        mounted = []
    })

    function mount(product: CustomFacetsProduct = 'logs'): ReturnType<typeof customFacetsLogic.build> {
        const logic = customFacetsLogic({ product })
        logic.mount()
        mounted.push(logic)
        return logic
    }

    it('does not load or expose custom facets when the feature flag is off', async () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        const logic = mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockRetrieve).not.toHaveBeenCalled()
        expect(logic.values.customFacetEntries).toEqual([])
    })

    it('loads entries when the flag arrives after mount', async () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        const logic = mount()
        expect(mockRetrieve).not.toHaveBeenCalled()

        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.CUSTOM_FACET_PINNING]: true })
        await expectLogic(logic).toDispatchActions(['loadEntries', 'loadEntriesSuccess'])
    })

    it.each(Object.values(UserFacetSettingsRetrieveProduct))(
        'mutations for %s build on the persisted list when entries have not loaded yet',
        async (product) => {
            // A PATCH replaces the whole server-side list — building it on unloaded local state would
            // wipe every facet the user pinned elsewhere.
            featureFlagLogic.actions.setFeatureFlags([], {})
            mockRetrieve.mockResolvedValue({ custom_facets: [{ key: 'pinned.elsewhere', source_type: ATTRIBUTE }] })
            const logic = mount(product)
            logic.actions.addCustomFacet('http.status_code', 'attribute')
            await expectLogic(logic).toDispatchActions(['addCustomFacetSuccess'])

            expect(mockRetrieve).toHaveBeenCalledWith('@me', { product })
            expect(mockPartialUpdate).toHaveBeenCalledWith(
                '@me',
                { product },
                {
                    custom_facets: [
                        { key: 'pinned.elsewhere', source_type: ATTRIBUTE },
                        { key: 'http.status_code', source_type: ATTRIBUTE },
                    ],
                }
            )
        }
    )

    it('keeps each product on its own list when both rails are mounted', async () => {
        mockRetrieve.mockImplementation(async (_uuid, { product }) => ({
            custom_facets: [{ key: `${product}.pinned`, source_type: ATTRIBUTE }],
        }))
        const logsLogic = mount('logs')
        const tracingLogic = mount('tracing')
        await expectLogic(logsLogic).toDispatchActions(['loadEntriesSuccess'])
        await expectLogic(tracingLogic).toDispatchActions(['loadEntriesSuccess'])

        tracingLogic.actions.addCustomFacet('http.route', 'attribute')
        await expectLogic(tracingLogic).toDispatchActions(['addCustomFacetSuccess'])

        expect(logsLogic.values.customFacetEntries).toEqual([{ key: 'logs.pinned', source_type: ATTRIBUTE }])
        expect(tracingLogic.values.customFacetEntries).toEqual([
            { key: 'tracing.pinned', source_type: ATTRIBUTE },
            { key: 'http.route', source_type: ATTRIBUTE },
        ])
    })

    it('loads persisted entries on mount', async () => {
        mockRetrieve.mockResolvedValue({ custom_facets: [{ key: 'log.iostream', source_type: ATTRIBUTE }] })
        const logic = mount()
        await expectLogic(logic).toDispatchActions(['loadEntriesSuccess'])

        expect(logic.values.customFacetEntries).toEqual([{ key: 'log.iostream', source_type: ATTRIBUTE }])
    })

    it('adding a facet persists the full updated list and updates local state', async () => {
        const logic = mount()
        logic.actions.addCustomFacet('log.iostream', 'attribute')
        await expectLogic(logic).toDispatchActions(['addCustomFacetSuccess'])

        expect(logic.values.entries).toEqual([{ key: 'log.iostream', source_type: ATTRIBUTE }])
        expect(mockPartialUpdate).toHaveBeenCalledWith(
            '@me',
            { product: 'logs' },
            { custom_facets: [{ key: 'log.iostream', source_type: ATTRIBUTE }] }
        )
    })

    it('adding the same key and sourceType twice does not duplicate or persist again', async () => {
        const logic = mount()
        logic.actions.addCustomFacet('log.iostream', 'attribute')
        await expectLogic(logic).toDispatchActions(['addCustomFacetSuccess'])
        mockPartialUpdate.mockClear()

        logic.actions.addCustomFacet('log.iostream', 'attribute')
        await expectLogic(logic).toDispatchActions(['addCustomFacetSuccess'])

        expect(logic.values.entries).toHaveLength(1)
        expect(mockPartialUpdate).not.toHaveBeenCalled()
    })

    it('removing a facet only drops the matching key+sourceType pair', async () => {
        // The same key can exist as both an attribute and a resource-attribute facet — removing one
        // must not also remove the other.
        const logic = mount()
        logic.actions.addCustomFacet('environment', 'attribute')
        await expectLogic(logic).toDispatchActions(['addCustomFacetSuccess'])
        logic.actions.addCustomFacet('environment', 'resourceAttribute')
        await expectLogic(logic).toDispatchActions(['addCustomFacetSuccess'])

        logic.actions.removeCustomFacet('environment', 'attribute')
        await expectLogic(logic).toDispatchActions(['removeCustomFacetSuccess'])

        expect(logic.values.entries).toEqual([{ key: 'environment', source_type: RESOURCE_ATTRIBUTE }])
    })
})
