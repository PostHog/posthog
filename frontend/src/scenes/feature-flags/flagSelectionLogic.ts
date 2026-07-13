import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { beforeUnload } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { pluralize } from 'lib/utils/strings'
import { projectLogic } from 'scenes/projectLogic'

import { featureFlagsLogic } from './featureFlagsLogic'
import type { flagSelectionLogicType } from './flagSelectionLogicType'

export type FlagRolloutState = 'fully_rolled_out' | 'not_rolled_out' | 'partial'

export interface DeletedFlagInfo {
    id: number
    key: string
    rollout_state: FlagRolloutState
    active_variant: string | null
}

export interface BulkDeleteResult {
    deleted: DeletedFlagInfo[]
    errors: Array<{ id: number; key?: string; reason: string }>
}

export interface BulkUpdateStatusResult {
    // Echoes the requested target state so the success toast can describe the direction (enable vs disable).
    active: boolean
    updated: Array<{ id: number; key: string; active: boolean }>
    errors: Array<{ id: number; key?: string; reason: string }>
}

export const flagSelectionLogic = kea<flagSelectionLogicType>([
    path(['scenes', 'feature-flags', 'flagSelectionLogic']),

    connect(() => ({
        values: [projectLogic, ['currentProjectId'], featureFlagsLogic({}), ['paramsFromFilters']],
        actions: [featureFlagsLogic({}), ['loadFeatureFlags']],
    })),

    actions({
        showResultsModal: (result: BulkDeleteResult) => ({ result }),
        hideResultsModal: true,
    }),

    reducers({
        bulkDeleteResult: [
            null as BulkDeleteResult | null,
            {
                showResultsModal: (_, { result }) => result,
                hideResultsModal: () => null,
            },
        ],
    }),

    loaders(({ values }) => ({
        bulkDeleteResponse: [
            null as BulkDeleteResult | null,
            {
                bulkDeleteFlags: async ({ ids, allMatching }: { ids: number[]; allMatching: boolean }) => {
                    if (allMatching) {
                        const { limit, offset, ...filters } = values.paramsFromFilters
                        const response = await api.create(
                            `api/projects/${values.currentProjectId}/feature_flags/bulk_delete/`,
                            { filters }
                        )
                        return response as BulkDeleteResult
                    }
                    const response = await api.create(
                        `api/projects/${values.currentProjectId}/feature_flags/bulk_delete/`,
                        { ids }
                    )
                    return response as BulkDeleteResult
                },
            },
        ],
        bulkUpdateStatusResponse: [
            null as BulkUpdateStatusResult | null,
            {
                bulkUpdateFlagStatus: async ({
                    ids,
                    active,
                    allMatching,
                }: {
                    ids: number[]
                    active: boolean
                    allMatching: boolean
                }) => {
                    const url = `api/projects/${values.currentProjectId}/feature_flags/bulk_update_status/`
                    // "Select all matching" resolves to filters (like bulk delete) so we don't ship an
                    // unbounded id list; an explicit selection sends the ids directly.
                    if (allMatching) {
                        const { limit, offset, ...filters } = values.paramsFromFilters
                        const response = (await api.create(url, { active, filters })) as Omit<
                            BulkUpdateStatusResult,
                            'active'
                        >
                        return { active, ...response }
                    }
                    const response = (await api.create(url, { active, ids })) as Omit<BulkUpdateStatusResult, 'active'>
                    return { active, ...response }
                },
            },
        ],
    })),

    selectors({
        resultsModalVisible: [(s) => [s.bulkDeleteResult], (result: BulkDeleteResult | null) => result !== null],
    }),

    listeners(({ actions }) => ({
        bulkDeleteFlagsSuccess: ({ bulkDeleteResponse }) => {
            if (bulkDeleteResponse) {
                actions.showResultsModal(bulkDeleteResponse)
                actions.loadFeatureFlags()
            }
        },
        bulkUpdateFlagStatusSuccess: ({ bulkUpdateStatusResponse }) => {
            if (!bulkUpdateStatusResponse) {
                return
            }
            const { active, updated, errors } = bulkUpdateStatusResponse
            if (updated.length > 0) {
                lemonToast.success(`${active ? 'Enabled' : 'Disabled'} ${pluralize(updated.length, 'feature flag')}`)
            }
            if (errors.length > 0) {
                lemonToast.warning(
                    `${pluralize(errors.length, 'feature flag')} could not be ${active ? 'enabled' : 'disabled'}`
                )
            }
            if (updated.length === 0 && errors.length === 0) {
                lemonToast.info('No feature flags needed updating')
            }
            actions.loadFeatureFlags()
        },
        bulkUpdateFlagStatusFailure: () => {
            lemonToast.error('Failed to update feature flag status')
        },
    })),

    beforeUnload(({ values }) => ({
        enabled: () => values.bulkDeleteResponseLoading || values.bulkUpdateStatusResponseLoading,
        message: 'A bulk action is in progress. Leaving may leave it incomplete.',
    })),
])
