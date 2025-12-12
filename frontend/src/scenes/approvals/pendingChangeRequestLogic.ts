import { actions, afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { ChangeRequest } from '~/types'

import type { pendingChangeRequestLogicType } from './pendingChangeRequestLogicType'

export interface PendingChangeRequestLogicProps {
    resourceType: string
    resourceId: string | number
    actionKey?: string
}

export const pendingChangeRequestLogic = kea<pendingChangeRequestLogicType>([
    path(['scenes', 'approvals', 'pendingChangeRequestLogic']),
    props({} as PendingChangeRequestLogicProps),
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

                    const response = await api.get(`api/projects/${values.currentTeamId}/change_requests`, params)
                    return response.results || []
                },
            },
        ],
    })),

    selectors({
        pendingChangeRequest: [
            (s) => [s.changeRequests],
            (changeRequests): ChangeRequest | null => {
                // Return the most recent pending or approved CR
                const pending = changeRequests.filter((cr) => cr.state === 'pending' || cr.state === 'approved')
                return pending.length > 0 ? pending[0] : null
            },
        ],

        shouldShowBanner: [
            (s) => [s.pendingChangeRequest],
            (pendingChangeRequest): boolean => {
                return pendingChangeRequest !== null
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        approveRequest: async ({ id }) => {
            try {
                const response = await api.create(
                    `api/projects/${values.currentTeamId}/change_requests/${id}/approve/`,
                    {}
                )

                // Check if it was auto-applied
                if (response.status === 'applied') {
                    lemonToast.success('Change request approved and applied successfully')

                    // Reload the page after 2 seconds to show the applied changes
                    setTimeout(() => {
                        window.location.reload()
                    }, 2000)
                } else if (response.status === 'failed') {
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
                await api.create(`api/projects/${values.currentTeamId}/change_requests/${id}/reject/`, { reason })
                lemonToast.success('Change request rejected')
                actions.loadChangeRequests()
            } catch (error: any) {
                lemonToast.error(error.detail || 'Failed to reject change request')
            }
        },

        cancelRequest: async ({ id, reason }) => {
            try {
                await api.create(`api/projects/${values.currentTeamId}/change_requests/${id}/cancel/`, { reason })
                lemonToast.success('Change request canceled')
                actions.loadChangeRequests()
            } catch (error: any) {
                lemonToast.error(error.detail || 'Failed to cancel change request')
            }
        },
    })),

    afterMount(({ actions, props }) => {
        actions.loadChangeRequests()

        // Set up event listener for change request creation
        const handleChangeRequestCreated = (event: CustomEvent): void => {
            const { resourceType, resourceId } = event.detail
            if (resourceType === props.resourceType && String(resourceId) === String(props.resourceId)) {
                actions.loadChangeRequests()
            }
        }

        window.addEventListener('change-request-created', handleChangeRequestCreated as EventListener)

        // Cleanup function
        return () => {
            window.removeEventListener('change-request-created', handleChangeRequestCreated as EventListener)
        }
    }),
])
