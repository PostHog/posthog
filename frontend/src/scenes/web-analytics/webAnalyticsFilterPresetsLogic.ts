import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api, { PaginatedResponse } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { toParams } from 'lib/utils'

import { WebAnalyticsFilterPresetType } from '~/types'

import { webAnalyticsFilterLogic } from './webAnalyticsFilterLogic'
import type { webAnalyticsFilterPresetsLogicType } from './webAnalyticsFilterPresetsLogicType'
import { webAnalyticsLogic } from './webAnalyticsLogic'

export const webAnalyticsFilterPresetsLogic = kea<webAnalyticsFilterPresetsLogicType>([
    path(['scenes', 'webAnalytics', 'webAnalyticsFilterPresetsLogic']),
    connect(() => ({
        values: [webAnalyticsLogic, ['currentFiltersConfig']],
        actions: [
            webAnalyticsFilterLogic,
            ['loadPreset', 'clearFilters as clearPropertyFilters'],
            webAnalyticsLogic,
            ['clearFilters as clearDateFilters'],
        ],
    })),
    actions({
        loadPresets: true,
        saveCurrentFiltersAsPreset: (name: string, description?: string) => ({ name, description }),
        applyPreset: (preset: WebAnalyticsFilterPresetType) => ({ preset }),
        deletePreset: (preset: WebAnalyticsFilterPresetType) => ({ preset }),
        updatePreset: (shortId: string, updates: Partial<WebAnalyticsFilterPresetType>) => ({ shortId, updates }),
        setAppliedPreset: (preset: WebAnalyticsFilterPresetType | null) => ({ preset }),
        clearPreset: true,
        checkForPresetRedirect: true,
        openSaveModal: true,
        closeSaveModal: true,
        setPresetFormName: (name: string) => ({ name }),
        setPresetFormDescription: (description: string) => ({ description }),
        resetPresetForm: true,
        openDeleteModal: (preset: WebAnalyticsFilterPresetType) => ({ preset }),
        closeDeleteModal: true,
    }),
    reducers({
        appliedPreset: [
            null as WebAnalyticsFilterPresetType | null,
            {
                setAppliedPreset: (_, { preset }) => preset,
                loadPreset: () => null,
                clearPreset: () => null,
            },
        ],
        saveModalOpen: [
            false,
            {
                openSaveModal: () => true,
                closeSaveModal: () => false,
                saveCurrentFiltersAsPresetSuccess: () => false,
            },
        ],
        presetFormName: [
            '',
            {
                setPresetFormName: (_, { name }) => name,
                resetPresetForm: () => '',
                saveCurrentFiltersAsPresetSuccess: () => '',
            },
        ],
        presetFormDescription: [
            '',
            {
                setPresetFormDescription: (_, { description }) => description,
                resetPresetForm: () => '',
                saveCurrentFiltersAsPresetSuccess: () => '',
            },
        ],
        presetToDelete: [
            null as WebAnalyticsFilterPresetType | null,
            {
                openDeleteModal: (_, { preset }) => preset,
                closeDeleteModal: () => null,
                deletePreset: () => null,
            },
        ],
    }),
    loaders(({ values, actions }) => ({
        presets: {
            __default: { results: [], count: 0 } as PaginatedResponse<WebAnalyticsFilterPresetType>,
            loadPresets: async () => {
                const params = {
                    order: '-last_modified_at',
                    limit: 20,
                }
                return await api.webAnalyticsFilterPresets.list(toParams(params))
            },
        },
        savedPreset: {
            __default: null as WebAnalyticsFilterPresetType | null,
            saveCurrentFiltersAsPreset: async ({ name, description }) => {
                const preset = await api.webAnalyticsFilterPresets.create({
                    name,
                    description: description || '',
                    filters: values.currentFiltersConfig,
                })
                actions.loadPresets()
                return preset
            },
            updatePreset: async ({ shortId, updates }) => {
                const updated = await api.webAnalyticsFilterPresets.update(shortId, updates)
                actions.loadPresets()
                return updated
            },
            deletePreset: async ({ preset }) => {
                await api.webAnalyticsFilterPresets.delete(preset.short_id)
                actions.loadPresets()
                return null
            },
        },
    })),
    listeners(({ actions, values }) => ({
        applyPreset: ({ preset }) => {
            if (values.appliedPreset?.short_id === preset.short_id) {
                actions.clearPreset()
                return
            }

            actions.loadPreset(preset.filters)
            actions.setAppliedPreset(preset)
        },
        checkForPresetRedirect: async () => {
            const { presetId } = router.values.searchParams
            if (presetId) {
                try {
                    const preset = await api.webAnalyticsFilterPresets.get(presetId)
                    if (preset) {
                        actions.applyPreset(preset)
                    }
                } catch {
                    lemonToast.error('Preset not found or has been deleted')

                    const { presetId: _, ...restParams } = router.values.searchParams
                    router.actions.replace(router.values.location.pathname, restParams)
                }
            }
        },
        closeSaveModal: () => {
            actions.resetPresetForm()
        },
        saveCurrentFiltersAsPresetSuccess: ({ savedPreset }) => {
            lemonToast.success(`Preset "${savedPreset.name}" saved`)
            actions.setAppliedPreset(savedPreset)
        },
        saveCurrentFiltersAsPresetFailure: ({ errorObject }) => {
            lemonToast.error(`Failed to save preset: ${errorObject?.detail || 'Unknown error'}`)
        },
        clearPreset: () => {
            actions.clearPropertyFilters()
            actions.clearDateFilters()
        },
        deletePreset: ({ preset }) => {
            if (values.appliedPreset?.short_id === preset.short_id) {
                actions.clearPreset()
            }
        },
    })),
    selectors({
        pinnedPresets: [
            (s) => [s.presets],
            (presets): WebAnalyticsFilterPresetType[] => {
                return presets.results.filter((p) => p.pinned)
            },
        ],
        recentPresets: [
            (s) => [s.presets],
            (presets): WebAnalyticsFilterPresetType[] => {
                return presets.results.filter((p) => !p.pinned).slice(0, 5)
            },
        ],
        hasPresets: [
            (s) => [s.presets],
            (presets): boolean => {
                return presets.results.length > 0
            },
        ],
        canSavePreset: [
            (s) => [s.presetFormName],
            (name): boolean => {
                return name.trim().length > 0
            },
        ],
        activePreset: [
            (s) => [s.appliedPreset],
            (appliedPreset): WebAnalyticsFilterPresetType | null => {
                if (!appliedPreset) {
                    return null
                }

                return appliedPreset
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadPresets()
        actions.checkForPresetRedirect()
    }),
])
