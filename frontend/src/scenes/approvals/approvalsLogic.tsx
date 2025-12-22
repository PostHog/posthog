import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api, { CountedPaginatedResponse } from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { ChangeRequest, ChangeRequestState } from '~/types'

import type { approvalsLogicType } from './approvalsLogicType'

export interface ApprovalsFilters {
    state?: ChangeRequestState
    action_type?: string
    resource_type?: string
    resource_id?: string
    requester?: number
}

export interface ApprovalDataState {
    changeRequests: ChangeRequest[]
    changeRequestsCount: number
}

function mergeChangeRequestsData(
    currentData: ApprovalDataState,
    response: CountedPaginatedResponse<ChangeRequest>,
    appendResults = false
): ApprovalDataState {
    // When appending (pagination), keep current data if no more results
    if (appendResults && response.results.length === 0) {
        return currentData
    }

    const changeRequests = appendResults ? [...currentData.changeRequests, ...response.results] : response.results

    return {
        ...currentData,
        changeRequests,
        changeRequestsCount: response.count ?? changeRequests.length,
    }
}

export const approvalsLogic = kea<approvalsLogicType>([
    path(['scenes', 'approvals', 'approvalsLogic']),
    connect({
        values: [teamLogic, ['currentTeamId']],
    }),
    actions({
        setFilters: (filters: Partial<ApprovalsFilters>) => ({ filters }),
        loadChangeRequests: (url?: string) => ({ url }),
        loadMore: true,
        approveChangeRequest: (id: string, reason?: string) => ({ id, reason }),
        rejectChangeRequest: (id: string, reason: string) => ({ id, reason }),
    }),
    loaders(({ values }) => ({
        changeRequestsData: [
            { changeRequests: [], changeRequestsCount: 0 } as ApprovalDataState,
            {
                loadChangeRequests: async ({ url }, breakpoint) => {
                    if (!values.currentTeamId) {
                        return values.changeRequestsData
                    }

                    await breakpoint(300)

                    const actualUrl =
                        url ||
                        `api/environments/${values.currentTeamId}/change_requests/?${new URLSearchParams({
                            ...(values.filters.state && { state: values.filters.state }),
                            ...(values.filters.action_type && { action_type: values.filters.action_type }),
                            ...(values.filters.resource_type && { resource_type: values.filters.resource_type }),
                            ...(values.filters.resource_id && { resource_id: values.filters.resource_id }),
                            ...(values.filters.requester && { requester: values.filters.requester.toString() }),
                        }).toString()}`

                    const response = await api.get<CountedPaginatedResponse<ChangeRequest>>(actualUrl)
                    breakpoint()

                    return mergeChangeRequestsData(values.changeRequestsData, response, !!url)
                },
            },
        ],
    })),
    reducers({
        filters: [
            { state: ChangeRequestState.Pending } as ApprovalsFilters,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
    }),
    selectors({
        changeRequests: [
            (s) => [s.changeRequestsData],
            (changeRequestsData): ChangeRequest[] => changeRequestsData.changeRequests,
        ],
        changeRequestsCount: [
            (s) => [s.changeRequestsData],
            (changeRequestsData): number => changeRequestsData.changeRequestsCount,
        ],
        hasMore: [
            (s) => [s.changeRequests, s.changeRequestsCount],
            (changeRequests, changeRequestsCount): boolean => {
                return changeRequests.length < changeRequestsCount
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        setFilters: async () => {
            actions.loadChangeRequests()
        },
        loadMore: async () => {
            const nextUrl = `api/environments/${values.currentTeamId}/change_requests/?${new URLSearchParams({
                offset: values.changeRequests.length.toString(),
                ...(values.filters.state && { state: values.filters.state }),
                ...(values.filters.action_type && { action_type: values.filters.action_type }),
                ...(values.filters.resource_type && { resource_type: values.filters.resource_type }),
                ...(values.filters.resource_id && { resource_id: values.filters.resource_id }),
                ...(values.filters.requester && { requester: values.filters.requester.toString() }),
            }).toString()}`

            actions.loadChangeRequests(nextUrl)
        },
        approveChangeRequest: async ({ id, reason }) => {
            try {
                await api.create(`api/environments/${values.currentTeamId}/change_requests/${id}/approve/`, {
                    reason: reason || '',
                })
                lemonToast.success('Change request approved')
                actions.loadChangeRequests()
            } catch (error: any) {
                lemonToast.error(error.detail || 'Failed to approve change request')
            }
        },
        rejectChangeRequest: async ({ id, reason }) => {
            try {
                await api.create(`api/environments/${values.currentTeamId}/change_requests/${id}/reject/`, {
                    reason,
                })
                lemonToast.success('Change request rejected')
                actions.loadChangeRequests()
            } catch (error: any) {
                lemonToast.error(error.detail || 'Failed to reject change request')
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadChangeRequests()
    }),
])
