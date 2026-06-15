import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { customProductsLogic } from '~/layout/panel-layout/ProjectTree/customProductsLogic'
import { getItemId } from '~/layout/panel-layout/ProjectTree/utils'
import { UserProductListItem, UserProductListReason } from '~/queries/schema/schema-general'

import type { inlineEditAppsLogicType } from './inlineEditAppsLogicType'

const PRODUCTS_ROOT = 'products://'

export const inlineEditAppsLogic = kea<inlineEditAppsLogicType>([
    path(['layout', 'panel-layout', 'ai-first', 'tabs', 'inlineEditAppsLogic']),
    connect(() => ({
        values: [customProductsLogic, ['customProducts']],
        actions: [customProductsLogic, ['loadCustomProducts', 'loadCustomProductsSuccess']],
    })),
    actions({
        enterEditMode: true,
        saveAndExitEditMode: true,
        toggleProduct: (productPath: string) => ({ productPath }),
        setLocalToggles: (toggles: Record<string, boolean>) => ({ toggles }),
    }),
    reducers({
        isEditMode: [
            false as boolean,
            {
                enterEditMode: () => true,
                saveAndExitEditMode: () => false,
            },
        ],
        localToggles: [
            {} as Record<string, boolean>,
            {
                enterEditMode: () => ({}),
                setLocalToggles: (_, { toggles }) => toggles,
            },
        ],
    }),
    selectors({
        selectedPaths: [
            (s) => [s.customProducts],
            (customProducts): Set<string> =>
                new Set(customProducts.map((item: { product_path: string }) => item.product_path)),
        ],
        checkedItems: [
            (s) => [s.customProducts, s.localToggles],
            (customProducts, localToggles): Record<string, boolean> => {
                const result: Record<string, boolean> = {}
                for (const item of customProducts) {
                    const id = getItemId({ path: item.product_path, type: '' }, PRODUCTS_ROOT)
                    result[id] = true
                }
                for (const [productPath, enabled] of Object.entries(localToggles)) {
                    const id = getItemId({ path: productPath, type: '' }, PRODUCTS_ROOT)
                    result[id] = enabled
                }
                return result
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        toggleProduct: ({ productPath }) => {
            const serverState = values.selectedPaths.has(productPath)
            const currentState = productPath in values.localToggles ? values.localToggles[productPath] : serverState
            const newState = !currentState

            const localToggles = { ...values.localToggles }
            if (newState === serverState) {
                delete localToggles[productPath]
            } else {
                localToggles[productPath] = newState
            }
            actions.setLocalToggles(localToggles)
        },
        saveAndExitEditMode: async () => {
            const toggles = values.localToggles
            const entries = Object.entries(toggles)

            if (entries.length > 0) {
                const now = new Date().toISOString()
                const existingPaths = new Set(values.customProducts.map((item) => item.product_path))
                const updated: UserProductListItem[] = values.customProducts.filter(
                    (item) => !(item.product_path in toggles) || toggles[item.product_path]
                )
                for (const [productPath, enabled] of entries) {
                    if (enabled && !existingPaths.has(productPath)) {
                        updated.push({
                            id: '',
                            product_path: productPath,
                            enabled: true,
                            reason: UserProductListReason.PRODUCT_INTENT,
                            reason_text: null,
                            created_at: now,
                            updated_at: now,
                        })
                    }
                }
                actions.loadCustomProductsSuccess(updated)

                try {
                    await api.userProductList.bulkUpdate(
                        entries.map(([productPath, enabled]) => ({ product_path: productPath, enabled }))
                    )
                } catch (error) {
                    console.error('Failed to save product changes:', error)
                    lemonToast.error('Failed to save some changes. Try again?')
                }
                // Refresh with real server data to replace optimistic placeholders
                actions.loadCustomProducts()
            }
        },
    })),
])
