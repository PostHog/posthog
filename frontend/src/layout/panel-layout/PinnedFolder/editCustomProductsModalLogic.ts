import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { customProductsLogic } from '~/layout/panel-layout/ProjectTree/customProductsLogic'
import { getDefaultTreeProducts } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemImport } from '~/queries/schema/schema-general'

import type { editCustomProductsModalLogicType } from './editCustomProductsModalLogicType'

export const editCustomProductsModalLogic = kea<editCustomProductsModalLogicType>([
    path(['layout', 'panel-layout', 'PinnedFolder', 'editCustomProductsModalLogic']),
    connect(() => ({
        values: [
            customProductsLogic,
            ['customProducts', 'customProductsLoading'],
            userLogic,
            ['user'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [
            customProductsLogic,
            ['loadCustomProducts', 'loadCustomProductsSuccess'],
            userLogic,
            ['updateUser', 'loadUserSuccess'],
        ],
    })),
    actions({
        toggleProduct: (productPath: string) => ({ productPath }),
        setAllowSidebarSuggestions: (value: boolean) => ({ value }),
        setSelectedPaths: (paths: Set<string>) => ({ paths }),
        save: true,
        setSaving: (saving: boolean) => ({ saving }),
        openModal: true,
        closeModal: true,
    }),
    reducers({
        isOpen: [
            false as boolean,
            {
                openModal: () => true,
                closeModal: () => false,
            },
        ],
        selectedPaths: [
            new Set<string>(),
            {
                toggleProduct: (state, { productPath }) => {
                    const newSelected = new Set(state)
                    if (newSelected.has(productPath)) {
                        newSelected.delete(productPath)
                    } else {
                        newSelected.add(productPath)
                    }
                    return newSelected
                },
                setSelectedPaths: (_, { paths }) => paths,
            },
        ],
        allowSidebarSuggestions: [
            false,
            {
                setAllowSidebarSuggestions: (_, { value }) => value,
            },
        ],
        saving: [
            false,
            {
                setSaving: (_, { saving }) => saving,
            },
        ],
    }),
    selectors({
        allProducts: [
            () => [],
            () => {
                return getDefaultTreeProducts().sort((a, b) => a.path.localeCompare(b.path || 'b'))
            },
        ],
        filteredProducts: [
            (s) => [s.allProducts, s.featureFlags],
            (allProducts: FileSystemImport[], featureFlags: Record<string, boolean>): FileSystemImport[] => {
                return allProducts.filter((f) => !f.flag || featureFlags[f.flag])
            },
        ],
        productsByCategory: [
            (s) => [s.filteredProducts],
            (filteredProducts: FileSystemImport[]): Map<string, FileSystemImport[]> => {
                const productsByCategory = new Map<string, FileSystemImport[]>()
                for (const product of filteredProducts) {
                    const category = product.category || 'Other'
                    if (!productsByCategory.has(category)) {
                        productsByCategory.set(category, [])
                    }
                    productsByCategory.get(category)!.push(product)
                }
                return productsByCategory
            },
        ],
        categories: [
            (s) => [s.productsByCategory],
            (productsByCategory: Map<string, FileSystemImport[]>): string[] => {
                return Array.from(productsByCategory.keys()).sort()
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        loadCustomProductsSuccess: ({ customProducts }) => {
            if (customProducts.length > 0) {
                actions.setSelectedPaths(
                    new Set(customProducts.map((item: { product_path: string }) => item.product_path))
                )
            }
        },
        loadUserSuccess: ({ user }) => {
            if (user) {
                actions.setAllowSidebarSuggestions(user.allow_sidebar_suggestions ?? false)
            }
        },
        save: async () => {
            actions.setSaving(true)
            try {
                await api.userProductList.bulkUpdate({ products: Array.from(values.selectedPaths) })

                if (values.user && values.user.allow_sidebar_suggestions !== values.allowSidebarSuggestions) {
                    actions.updateUser({ allow_sidebar_suggestions: values.allowSidebarSuggestions })
                }

                actions.loadCustomProducts()
            } catch (error) {
                console.error('Failed to save custom products:', error)
                lemonToast.error('Failed to save custom products. Try again?')
            } finally {
                actions.setSaving(false)
            }
        },
    })),
    afterMount(({ actions, values }) => {
        if (values.user) {
            actions.setAllowSidebarSuggestions(values.user.allow_sidebar_suggestions ?? false)
        }

        if (values.customProducts.length > 0) {
            actions.setSelectedPaths(
                new Set(values.customProducts.map((item: { product_path: string }) => item.product_path))
            )
        }
    }),
])
