import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { beforeUnload } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { pluralize } from 'lib/utils/strings'
import { organizationLogic } from 'scenes/organizationLogic'
import { projectLogic } from 'scenes/projectLogic'

import type { CopyFlagsResultApi } from 'products/feature_flags/frontend/generated/api.schemas'

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

export const BULK_COPY_MAX_FLAGS = 100
export const BULK_COPY_MAX_TARGET_PROJECTS = 50

export interface BulkCopyParams {
    /** Project the flags are copied from. */
    sourceProjectId: number
    /** Selected flag IDs (overview tab) — resolved to keys via bulk_keys at submit time. */
    flagIds?: number[]
    /** Selected flag keys (projects grid) — used as-is. */
    flagKeys?: string[]
    /** Whether the modal lets the user change the source project (projects grid rows are org-level). */
    sourceSelectable?: boolean
}

export interface BulkCopyFailure {
    key: string
    projectId: number | null
    errorMessage: string
    /** The copy wasn't applied because the target project requires approval — a change request was created. */
    approvalPending?: boolean
}

export interface BulkCopyResult {
    copied: Array<{
        key: string
        projectIds: number[]
        /** Subset of projectIds where a flag with this key already existed and was overwritten. */
        updatedProjectIds: number[]
    }>
    failed: BulkCopyFailure[]
    warnings: string[]
    /** Selected flags that no longer resolved to a key (e.g. deleted between selection and submit). */
    skippedFlagCount: number
}

function errorMessageFrom(error: unknown): string {
    if (typeof error === 'string') {
        return error
    }
    if (error && typeof error === 'object') {
        const { detail, message } = error as { detail?: unknown; message?: unknown }
        if (typeof detail === 'string') {
            return detail
        }
        if (typeof message === 'string') {
            return message
        }
        return JSON.stringify(error)
    }
    return 'Request failed'
}

export const flagSelectionLogic = kea<flagSelectionLogicType>([
    path(['scenes', 'feature-flags', 'flagSelectionLogic']),

    connect(() => ({
        values: [
            projectLogic,
            ['currentProjectId'],
            featureFlagsLogic({}),
            ['paramsFromFilters'],
            organizationLogic,
            ['currentOrganization'],
        ],
        actions: [featureFlagsLogic({}), ['loadFeatureFlags'], eventUsageLogic, ['reportFeatureFlagBulkCopy']],
    })),

    actions({
        showResultsModal: (result: BulkDeleteResult) => ({ result }),
        hideResultsModal: true,
        openBulkCopyModal: (params: BulkCopyParams) => ({ params }),
        closeBulkCopyModal: true,
        setBulkCopySourceProjectId: (projectId: number) => ({ projectId }),
        setBulkCopyTargetProjectIds: (projectIds: number[]) => ({ projectIds }),
        setBulkCopySchedule: (copySchedule: boolean) => ({ copySchedule }),
        setBulkCopyDisableCopiedFlag: (disableCopiedFlag: boolean) => ({ disableCopiedFlag }),
        setBulkCopyProgress: (done: number, total: number) => ({ done, total }),
        bulkCopyFlags: true,
        bulkCopyFlagsFinished: (result: BulkCopyResult | null) => ({ result }),
    }),

    reducers({
        bulkDeleteResult: [
            null as BulkDeleteResult | null,
            {
                showResultsModal: (_, { result }) => result,
                hideResultsModal: () => null,
            },
        ],
        bulkCopyParams: [
            null as BulkCopyParams | null,
            {
                openBulkCopyModal: (_, { params }) => params,
                closeBulkCopyModal: () => null,
            },
        ],
        bulkCopySourceProjectId: [
            null as number | null,
            {
                openBulkCopyModal: (_, { params }) => params.sourceProjectId,
                setBulkCopySourceProjectId: (_, { projectId }) => projectId,
            },
        ],
        bulkCopyTargetProjectIds: [
            [] as number[],
            {
                openBulkCopyModal: () => [],
                setBulkCopyTargetProjectIds: (_, { projectIds }) => projectIds,
                // A project can't be both source and destination of the same copy
                setBulkCopySourceProjectId: (state, { projectId }) => state.filter((id) => id !== projectId),
            },
        ],
        bulkCopySchedule: [
            false,
            {
                openBulkCopyModal: () => false,
                setBulkCopySchedule: (_, { copySchedule }) => copySchedule,
            },
        ],
        bulkCopyDisableCopiedFlag: [
            false,
            {
                openBulkCopyModal: () => false,
                setBulkCopyDisableCopiedFlag: (_, { disableCopiedFlag }) => disableCopiedFlag,
            },
        ],
        bulkCopyRunning: [
            false,
            {
                bulkCopyFlags: () => true,
                bulkCopyFlagsFinished: () => false,
            },
        ],
        bulkCopyProgress: [
            null as { done: number; total: number } | null,
            {
                openBulkCopyModal: () => null,
                setBulkCopyProgress: (_, { done, total }) => ({ done, total }),
            },
        ],
        bulkCopyResult: [
            null as BulkCopyResult | null,
            {
                openBulkCopyModal: () => null,
                bulkCopyFlagsFinished: (_, { result }) => result,
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
    })),

    selectors({
        resultsModalVisible: [(s) => [s.bulkDeleteResult], (result: BulkDeleteResult | null) => result !== null],
        bulkCopyModalVisible: [(s) => [s.bulkCopyParams], (params: BulkCopyParams | null) => params !== null],
        bulkCopyFlagCount: [
            (s) => [s.bulkCopyParams],
            (params: BulkCopyParams | null): number => params?.flagKeys?.length ?? params?.flagIds?.length ?? 0,
        ],
    }),

    listeners(({ actions, values }) => ({
        bulkDeleteFlagsSuccess: ({ bulkDeleteResponse }) => {
            if (bulkDeleteResponse) {
                actions.showResultsModal(bulkDeleteResponse)
                actions.loadFeatureFlags()
            }
        },
        bulkCopyFlags: async () => {
            const params = values.bulkCopyParams
            const sourceProjectId = values.bulkCopySourceProjectId
            const targetProjectIds = values.bulkCopyTargetProjectIds
            if (!params || !sourceProjectId || targetProjectIds.length === 0) {
                actions.bulkCopyFlagsFinished(null)
                return
            }

            let keys: string[] = []
            let skippedFlagCount = 0
            try {
                if (params.flagKeys?.length) {
                    keys = Array.from(new Set(params.flagKeys))
                } else if (params.flagIds?.length) {
                    const response = await api.featureFlags.bulkKeys(params.flagIds)
                    keys = Array.from(new Set(Object.values(response.keys)))
                    skippedFlagCount = params.flagIds.length - Object.keys(response.keys).length
                }
            } catch (error) {
                lemonToast.error(`Failed to resolve selected flags: ${errorMessageFrom(error)}`)
                actions.bulkCopyFlagsFinished(null)
                return
            }
            if (keys.length === 0) {
                lemonToast.error('None of the selected flags could be resolved — they may have been deleted.')
                actions.bulkCopyFlagsFinished(null)
                return
            }
            if (keys.length > BULK_COPY_MAX_FLAGS) {
                lemonToast.error(`Bulk copy supports up to ${BULK_COPY_MAX_FLAGS} flags at once.`)
                actions.bulkCopyFlagsFinished(null)
                return
            }

            const copied: BulkCopyResult['copied'] = []
            const failed: BulkCopyFailure[] = []
            const warnings = new Set<string>()

            actions.setBulkCopyProgress(0, keys.length)
            // Sequential on purpose: each call already fans out to every target project server-side
            // (and may create cohorts there), so parallel calls would multiply write load and risk
            // rate limiting without improving perceived progress.
            for (const [index, key] of keys.entries()) {
                try {
                    const response = await api.organizationFeatureFlags.copy(values.currentOrganization?.id, {
                        feature_flag_key: key,
                        from_project: sourceProjectId,
                        target_project_ids: targetProjectIds,
                        copy_schedule: values.bulkCopySchedule,
                        disable_copied_flag: values.bulkCopyDisableCopiedFlag,
                    })
                    const failedEntries: CopyFlagsResultApi[] = Array.isArray(response.failed) ? response.failed : []
                    // Copied targets are inferred as requested-minus-failed (robust to success items
                    // missing team_id during deploy skew); overwrites come from the per-item flag.
                    const failedProjectIds = new Set(failedEntries.map((entry) => entry.project_id))
                    const copiedProjectIds = targetProjectIds.filter((id) => !failedProjectIds.has(id))
                    const updatedProjectIds = response.success
                        .filter((item) => item.updated_existing && item.team_id != null)
                        .map((item) => item.team_id as number)
                    if (copiedProjectIds.length > 0) {
                        copied.push({ key, projectIds: copiedProjectIds, updatedProjectIds })
                    }
                    for (const entry of failedEntries) {
                        failed.push({
                            key,
                            projectId: entry.project_id ?? null,
                            errorMessage: errorMessageFrom(entry.error_message ?? 'Copy failed'),
                            approvalPending: entry.approval_pending,
                        })
                    }
                    for (const successItem of response.success) {
                        for (const warning of successItem.flag_dependency_warnings ?? []) {
                            warnings.add(`${key}: ${warning}`)
                        }
                        if (successItem.schedule_copy_warning) {
                            warnings.add(`${key}: ${successItem.schedule_copy_warning}`)
                        }
                    }
                } catch (error) {
                    for (const projectId of targetProjectIds) {
                        failed.push({ key, projectId, errorMessage: errorMessageFrom(error) })
                    }
                }
                actions.setBulkCopyProgress(index + 1, keys.length)
            }

            actions.bulkCopyFlagsFinished({
                copied,
                failed,
                warnings: Array.from(warnings),
                skippedFlagCount,
            })
            actions.reportFeatureFlagBulkCopy(keys.length, targetProjectIds.length, failed.length)

            const pendingApprovalCount = failed.filter((failure) => failure.approvalPending).length
            const hardFailureCount = failed.length - pendingApprovalCount
            const updatedPairCount = copied.reduce((count, entry) => count + entry.updatedProjectIds.length, 0)
            const summary =
                `Copied ${pluralize(copied.length, 'flag')} to ${pluralize(targetProjectIds.length, 'project')}` +
                (updatedPairCount > 0 ? ` (${pluralize(updatedPairCount, 'existing flag')} overwritten)` : '')
            if (failed.length === 0 && copied.length > 0) {
                lemonToast.success(summary)
            } else if (copied.length > 0 || pendingApprovalCount > 0) {
                lemonToast.warning(
                    `${summary}${pendingApprovalCount > 0 ? `, ${pendingApprovalCount} pending approval` : ''}${
                        hardFailureCount > 0 ? `, ${hardFailureCount} failed` : ''
                    }`
                )
            } else {
                lemonToast.error('No flags were copied')
            }
        },
    })),

    beforeUnload(({ values }) => ({
        enabled: () => values.bulkDeleteResponseLoading || values.bulkCopyRunning,
        message: 'A bulk flag operation is in progress. Leaving may interrupt it.',
    })),
])
