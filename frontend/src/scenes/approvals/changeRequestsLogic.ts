import { actions, afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { ChangeRequest, ChangeRequestState } from '~/types'

import type { changeRequestsLogicType } from './changeRequestsLogicType'

export interface ChangeRequestsLogicProps {
    resourceType: string
    resourceId: string | number
    actionKey?: string
}

export interface ChangeRequestButtonVisibility {
    showApproveButton: boolean
    showRejectButton: boolean
    showCancelButton: boolean
}

export function getChangeRequestButtonVisibility(changeRequest: ChangeRequest): ChangeRequestButtonVisibility {
    const isPending = changeRequest.state === ChangeRequestState.Pending
    const canApprove = changeRequest.can_approve
    const canCancel = changeRequest.can_cancel
    const isRequester = changeRequest.is_requester
    const hasVoted = !!changeRequest.user_decision

    return {
        showApproveButton: isPending && canApprove && !hasVoted,
        showRejectButton: isPending && canApprove && !isRequester && !hasVoted,
        showCancelButton: isPending && isRequester && canCancel,
    }
}

export const changeRequestsLogic = kea<changeRequestsLogicType>([
    path(['scenes', 'approvals', 'changeRequestsLogic']),
    props({} as ChangeRequestsLogicProps),
    key((props) => `${props.resourceType}-${props.resourceId}`),

    connect({
        values: [teamLogic, ['currentTeamId']],
    }),

    actions({
        loadChangeRequests: true,
        approveRequest: (id: string) => ({ id }),
        rejectRequest: (id: string, reason?: string) => ({ id, reason }),
        cancelRequest: (id: string, reason?: string) => ({ id, reason }),
    }),

    loaders(({ props, values }) => ({
        changeRequests: [
            [] as ChangeRequest[],
            {
                loadChangeRequests: async () => {
                    if (!values.currentTeamId) {
                        return []
                    }

                    const params: Record<string, string> = {
                        resource_type: props.resourceType,
                        resource_id: String(props.resourceId),
                        state: 'pending,approved',
                    }

                    if (props.actionKey) {
                        params.action_key = props.actionKey
                    }

                    const response = await api.get(`api/environments/${values.currentTeamId}/change_requests`, params)
                    return response.results || []
                },
            },
        ],
    })),

    selectors({
        pendingChangeRequest: [
            (s) => [s.changeRequests],
            (changeRequests): ChangeRequest | null => {
                const pending = changeRequests.filter(
                    (cr) => cr.state === ChangeRequestState.Pending || cr.state === ChangeRequestState.Approved
                )
                return pending.length > 0 ? pending[0] : null
            },
        ],

        shouldShowBanner: [
            (s) => [s.pendingChangeRequest],
            (pendingChangeRequest): boolean => {
                return pendingChangeRequest !== null
            },
        ],

        buttonVisibility: [
            (s) => [s.pendingChangeRequest],
            (pendingChangeRequest): ChangeRequestButtonVisibility | null => {
                if (!pendingChangeRequest) {
                    return null
                }
                return getChangeRequestButtonVisibility(pendingChangeRequest)
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        approveRequest: async ({ id }) => {
            try {
                const response = await api.create(
                    `api/environments/${values.currentTeamId}/change_requests/${id}/approve/`,
                    {}
                )

                if (response.status === ChangeRequestState.Applied) {
                    lemonToast.success('Change request approved and applied successfully')

                    setTimeout(() => {
                        window.location.reload()
                    }, 2000)
                } else if (response.status === ChangeRequestState.Failed) {
                    lemonToast.error(`Approval succeeded but application failed: ${response.message}`)
                    actions.loadChangeRequests()
                } else {
                    lemonToast.success(response.message || 'Change request approved')
                    actions.loadChangeRequests()
                }
            } catch (error: any) {
                lemonToast.error(error.detail || 'Failed to approve change request')
            }
        },

        rejectRequest: async ({ id, reason }) => {
            try {
                await api.create(`api/environments/${values.currentTeamId}/change_requests/${id}/reject/`, { reason })
                lemonToast.success('Change request rejected')
                actions.loadChangeRequests()
            } catch (error: any) {
                lemonToast.error(error.detail || 'Failed to reject change request')
            }
        },

        cancelRequest: async ({ id, reason }) => {
            try {
                await api.create(`api/environments/${values.currentTeamId}/change_requests/${id}/cancel/`, { reason })
                lemonToast.success('Change request canceled')
                actions.loadChangeRequests()
            } catch (error: any) {
                lemonToast.error(error.detail || 'Failed to cancel change request')
            }
        },
    })),

    afterMount(({ actions, props }) => {
        actions.loadChangeRequests()

        const handleChangeRequestCreated = (event: CustomEvent): void => {
            const { resourceType, resourceId } = event.detail
            if (resourceType === props.resourceType && String(resourceId) === String(props.resourceId)) {
                actions.loadChangeRequests()
            }
        }

        window.addEventListener('change-request-created', handleChangeRequestCreated as EventListener)

        return () => {
            window.removeEventListener('change-request-created', handleChangeRequestCreated as EventListener)
        }
    }),
])
