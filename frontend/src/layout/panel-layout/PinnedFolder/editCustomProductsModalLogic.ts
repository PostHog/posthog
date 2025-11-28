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
        setProductLoading: (productPath: string, loading: boolean) => ({ productPath, loading }),
        setSidebarSuggestionsLoading: (loading: boolean) => ({ loading }),
        toggleSidebarSuggestions: true,
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
                setSelectedPaths: (_, { paths }) => paths,
                toggleProduct: (state, { productPath }) => {
                    const newState = new Set(state)
                    if (newState.has(productPath)) {
                        newState.delete(productPath)
                    } else {
                        newState.add(productPath)
                    }
                    return newState
                },
            },
        ],
        allowSidebarSuggestions: [
            false,
            {
                setAllowSidebarSuggestions: (_, { value }) => value,
                toggleSidebarSuggestions: (state) => !state,
            },
        ],
        sidebarSuggestionsLoading: [
            false,
            {
                setSidebarSuggestionsLoading: (_, { loading }) => loading,
                toggleSidebarSuggestions: () => true,
            },
        ],
        productLoading: [
            {} as Record<string, boolean>,
            {
                setProductLoading: (state, { productPath, loading }) => {
                    const newState = { ...state }
                    if (loading) {
                        newState[productPath] = true
                    } else {
                        delete newState[productPath]
                    }
                    return newState
                },
            },
        ],
        allProducts: [getDefaultTreeProducts().sort((a, b) => a.path.localeCompare(b.path || 'b')), {}],
    }),
    selectors({
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
            actions.setSelectedPaths(new Set(customProducts.map((item: { product_path: string }) => item.product_path)))
        },
        loadUserSuccess: ({ user }) => {
            if (user) {
                actions.setAllowSidebarSuggestions(user.allow_sidebar_suggestions ?? false)
            }
        },
        toggleProduct: async ({ productPath }) => {
            // State is updated already in the store
            const newEnabledState = values.selectedPaths.has(productPath)

            try {
                actions.setProductLoading(productPath, true)
                await api.userProductList.updateByPath({ product_path: productPath, enabled: newEnabledState })
            } catch (error) {
                console.error('Failed to toggle product:', error)
                lemonToast.error('Failed to toggle product. Try again?')

                // Revert state
                actions.setSelectedPaths(
                    new Set(Array.from(values.selectedPaths).filter((path) => path !== productPath))
                )
            } finally {
                actions.loadCustomProducts()
                actions.setProductLoading(productPath, false)
            }
        },
        toggleSidebarSuggestions: () => {
            try {
                actions.setSidebarSuggestionsLoading(true)
                actions.updateUser({ allow_sidebar_suggestions: values.allowSidebarSuggestions }) // Store is updated already
            } catch (error) {
                console.error('Failed to save sidebar suggestions preference:', error)
                lemonToast.error('Failed to save preference. Try again?')
            } finally {
                actions.setSidebarSuggestionsLoading(false)
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
