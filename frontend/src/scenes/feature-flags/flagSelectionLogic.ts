import { MakeLogicType, actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { beforeUnload } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { pluralize } from 'lib/utils/strings'
import { organizationLogic } from 'scenes/organizationLogic'
import { projectLogic } from 'scenes/projectLogic'

import type { CopyFlagsResponseApi } from 'products/feature_flags/frontend/generated/api.schemas'

import type { OrganizationType } from '../../types'
import { featureFlagsLogic } from './featureFlagsLogic'

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
// Mirrors MAX_COPY_FLAGS_TARGET_PROJECTS in
// products/feature_flags/backend/api/organization_feature_flag.py, which rejects more. Keep in sync.
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

function summarizeBulkCopy(
    copied: BulkCopyResult['copied'],
    failed: BulkCopyFailure[],
    targetCount: number
): { level: 'success' | 'warning' | 'error'; message: string } {
    const pendingApprovalCount = failed.filter((failure) => failure.approvalPending).length
    const hardFailureCount = failed.length - pendingApprovalCount
    const updatedPairCount = copied.reduce((count, entry) => count + entry.updatedProjectIds.length, 0)
    // Omit the "Copied N flags" clause entirely when nothing copied, rather than showing a
    // contradictory "Copied 0 flags ... pending approval" message.
    const summary =
        copied.length > 0
            ? `Copied ${pluralize(copied.length, 'flag')} to ${pluralize(targetCount, 'project')}` +
              (updatedPairCount > 0 ? ` (${pluralize(updatedPairCount, 'existing flag')} overwritten)` : '')
            : null
    if (failed.length === 0 && copied.length > 0) {
        return { level: 'success', message: summary as string }
    }
    if (copied.length > 0 || pendingApprovalCount > 0) {
        const parts = [
            summary,
            pendingApprovalCount > 0 ? `${pluralize(pendingApprovalCount, 'copy', 'copies')} pending approval` : null,
            hardFailureCount > 0 ? `${pluralize(hardFailureCount, 'copy', 'copies')} failed` : null,
        ].filter((part): part is string => part !== null)
        return {
            level: 'warning',
            message: parts.join(', '),
        }
    }
    return { level: 'error', message: 'No flags were copied' }
}

function errorMessageFrom(error: unknown): string {
    if (typeof error === 'string') {
        return error
    }
    if (error instanceof ApiError) {
        return error.detail ?? error.message
    }
    return 'Request failed'
}

/** Turns one key's copy response into the copied/failed/warning entries the bulk-copy listener accumulates. */
function aggregateCopyResponse(
    key: string,
    targetProjectIds: number[],
    response: CopyFlagsResponseApi
): { copied: BulkCopyResult['copied'][number] | null; failed: BulkCopyFailure[]; warnings: string[] } {
    // Copied targets are inferred as requested-minus-failed (robust to success items
    // missing team_id during deploy skew); overwrites come from the per-item flag.
    const failedProjectIds = new Set(
        response.failed.map((entry) => entry.project_id).filter((id): id is number => id != null)
    )
    const copiedProjectIds = targetProjectIds.filter((id) => !failedProjectIds.has(id))
    const updatedProjectIds = response.success
        .filter((item) => item.updated_existing && item.team_id != null)
        .map((item) => item.team_id)
    const failed: BulkCopyFailure[] = response.failed.map((entry) => ({
        key,
        projectId: entry.project_id ?? null,
        errorMessage: errorMessageFrom(entry.error_message || 'Copy failed'),
        approvalPending: entry.approval_pending,
    }))
    const warnings: string[] = []
    for (const successItem of response.success) {
        for (const warning of successItem.flag_dependency_warnings ?? []) {
            warnings.push(`${key}: ${warning}`)
        }
        if (successItem.schedule_copy_warning) {
            warnings.push(`${key}: ${successItem.schedule_copy_warning}`)
        }
    }
    return {
        copied: copiedProjectIds.length > 0 ? { key, projectIds: copiedProjectIds, updatedProjectIds } : null,
        failed,
        warnings,
    }
}

/** Splits each copied entry's projectIds into freshly created flags vs. overwrites of flags that already existed in the target. */
export function splitCopiedByOverwrite(copied: BulkCopyResult['copied']): {
    newCopies: Array<{ key: string; projectIds: number[] }>
    overwrites: Array<{ key: string; projectIds: number[] }>
} {
    const newCopies = copied
        .map((entry) => ({
            key: entry.key,
            projectIds: entry.projectIds.filter((id) => !entry.updatedProjectIds.includes(id)),
        }))
        .filter((entry) => entry.projectIds.length > 0)
    const overwrites = copied
        .map((entry) => ({ key: entry.key, projectIds: entry.updatedProjectIds }))
        .filter((entry) => entry.projectIds.length > 0)
    return { newCopies, overwrites }
}

export function getBulkCopyDisabledReason(selectedCount: number, extraReason?: string | null): string | undefined {
    if (extraReason) {
        return extraReason
    }
    if (selectedCount > BULK_COPY_MAX_FLAGS) {
        return `Bulk copy supports up to ${BULK_COPY_MAX_FLAGS} flags at once`
    }
    return undefined
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface flagSelectionLogicValues {
    paramsFromFilters: {
        active?: string | undefined
        archived?: string | undefined
        created_by_id?: number[] | undefined
        evaluation_runtime?: string | undefined
        excluded_tags?: string[] | undefined
        limit: number
        offset: number
        order?: string | undefined
        page?: number | undefined
        search?: string | undefined
        tags?: string[] | undefined
        type?: string | undefined
    } // featureFlagsLogic
    currentOrganization: OrganizationType | null // organizationLogic
    currentProjectId: number | null // projectLogic
    bulkCopyDisableCopiedFlag: boolean
    bulkCopyFlagCount: number
    bulkCopyHardFailures: BulkCopyFailure[]
    bulkCopyModalVisible: boolean
    bulkCopyParams: BulkCopyParams | null
    bulkCopyPendingApproval: BulkCopyFailure[]
    bulkCopyProgress: {
        done: number
        total: number
    } | null
    bulkCopyResult: BulkCopyResult | null
    bulkCopyRunning: boolean
    bulkCopySchedule: boolean
    bulkCopySourceProjectId: number | null
    bulkCopySplitCopied: {
        newCopies: {
            key: string
            projectIds: number[]
        }[]
        overwrites: {
            key: string
            projectIds: number[]
        }[]
    }
    bulkCopySubmitDisabledReason: string | undefined
    bulkCopyTargetProjectIds: number[]
    bulkDeleteResponse: BulkDeleteResult | null
    bulkDeleteResponseLoading: boolean
    bulkDeleteResult: BulkDeleteResult | null
    resultsModalVisible: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface flagSelectionLogicActions {
    reportFeatureFlagBulkCopy: (
        flagCount: number,
        projectCount: number,
        failedCount: number
    ) => {
        failedCount: number
        flagCount: number
        projectCount: number
    } // eventUsageLogic
    loadFeatureFlags: () => any // featureFlagsLogic
    bulkCopyFlags: () => {
        value: true
    }
    bulkCopyFlagsFinished: (result: BulkCopyResult | null) => {
        result: BulkCopyResult | null
    }
    bulkDeleteFlags: ({ ids, allMatching }: { allMatching: boolean; ids: number[] }) => {
        ids: number[]
        allMatching: boolean
    }
    bulkDeleteFlagsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    bulkDeleteFlagsSuccess: (
        bulkDeleteResponse: BulkDeleteResult,
        payload?: {
            ids: number[]
            allMatching: boolean
        }
    ) => {
        bulkDeleteResponse: BulkDeleteResult
        payload?: {
            ids: number[]
            allMatching: boolean
        }
    }
    closeBulkCopyModal: () => {
        value: true
    }
    hideResultsModal: () => {
        value: true
    }
    openBulkCopyModal: (params: BulkCopyParams) => {
        params: BulkCopyParams
    }
    setBulkCopyDisableCopiedFlag: (disableCopiedFlag: boolean) => {
        disableCopiedFlag: boolean
    }
    setBulkCopyProgress: (
        done: number,
        total: number
    ) => {
        done: number
        total: number
    }
    setBulkCopySchedule: (copySchedule: boolean) => {
        copySchedule: boolean
    }
    setBulkCopySourceProjectId: (projectId: number) => {
        projectId: number
    }
    setBulkCopyTargetProjectIds: (projectIds: number[]) => {
        projectIds: number[]
    }
    showResultsModal: (result: BulkDeleteResult) => {
        result: BulkDeleteResult
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface flagSelectionLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        resultsModalVisible: (bulkDeleteResult: BulkDeleteResult | null) => boolean
        bulkCopyModalVisible: (bulkCopyParams: BulkCopyParams | null) => boolean
        bulkCopyFlagCount: (bulkCopyParams: BulkCopyParams | null) => number
        bulkCopySplitCopied: (bulkCopyResult: BulkCopyResult | null) => {
            newCopies: {
                key: string
                projectIds: number[]
            }[]
            overwrites: {
                key: string
                projectIds: number[]
            }[]
        }
        bulkCopyPendingApproval: (bulkCopyResult: BulkCopyResult | null) => BulkCopyFailure[]
        bulkCopyHardFailures: (bulkCopyResult: BulkCopyResult | null) => BulkCopyFailure[]
        bulkCopySubmitDisabledReason: (bulkCopyTargetProjectIds: number[]) => string | undefined
    }
}

export type flagSelectionLogicType = MakeLogicType<
    flagSelectionLogicValues,
    flagSelectionLogicActions,
    Record<string, any>,
    flagSelectionLogicMeta
>

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
        bulkCopySplitCopied: [
            (s) => [s.bulkCopyResult],
            (result: BulkCopyResult | null) => splitCopiedByOverwrite(result?.copied ?? []),
        ],
        bulkCopyPendingApproval: [
            (s) => [s.bulkCopyResult],
            (result: BulkCopyResult | null): BulkCopyFailure[] =>
                result?.failed.filter((failure) => failure.approvalPending) ?? [],
        ],
        bulkCopyHardFailures: [
            (s) => [s.bulkCopyResult],
            (result: BulkCopyResult | null): BulkCopyFailure[] =>
                result?.failed.filter((failure) => !failure.approvalPending) ?? [],
        ],
        bulkCopySubmitDisabledReason: [
            (s) => [s.bulkCopyTargetProjectIds],
            (targetProjectIds: number[]): string | undefined =>
                targetProjectIds.length === 0
                    ? 'Select at least one destination project'
                    : targetProjectIds.length > BULK_COPY_MAX_TARGET_PROJECTS
                      ? `Bulk copy supports up to ${BULK_COPY_MAX_TARGET_PROJECTS} destination projects at once`
                      : undefined,
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
                    const aggregated = aggregateCopyResponse(key, targetProjectIds, response)
                    if (aggregated.copied) {
                        copied.push(aggregated.copied)
                    }
                    failed.push(...aggregated.failed)
                    aggregated.warnings.forEach((warning) => warnings.add(warning))
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

            const { level, message } = summarizeBulkCopy(copied, failed, targetProjectIds.length)
            lemonToast[level](message)
        },
    })),

    beforeUnload(({ values }) => ({
        enabled: () => values.bulkDeleteResponseLoading || values.bulkCopyRunning,
        message: 'A bulk flag operation is in progress. Leaving may interrupt it.',
    })),
])
