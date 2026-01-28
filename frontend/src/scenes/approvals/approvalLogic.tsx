import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { getApprovalActionLabel } from 'scenes/approvals/utils'
import { membersLogic } from 'scenes/organization/membersLogic'
import { Scene } from 'scenes/sceneTypes'
import { rolesLogic } from 'scenes/settings/organization/Permissions/Roles/rolesLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb, ChangeRequest, ChangeRequestState } from '~/types'

import type { approvalLogicType } from './approvalLogicType'

export interface ApprovalLogicProps {
    id: string
}

export type ProposedChangesTab = 'gated' | 'full'

export const approvalLogic = kea<approvalLogicType>([
    path(['scenes', 'approvals', 'approvalLogic']),
    props({} as ApprovalLogicProps),
    key(({ id }) => id),
    connect({
        values: [teamLogic, ['currentTeamId']],
        actions: [membersLogic, ['loadAllMembers'], rolesLogic, ['loadRoles']],
    }),
    actions({
        loadChangeRequest: true,
        approveChangeRequest: (reason?: string) => ({ reason }),
        rejectChangeRequest: (reason: string) => ({ reason }),
        cancelChangeRequest: (reason?: string) => ({ reason }),
        setProposedChangesTab: (tab: ProposedChangesTab) => ({ tab }),
    }),
    loaders(({ props, values }) => ({
        changeRequest: [
            null as ChangeRequest | null,
            {
                loadChangeRequest: async () => {
                    if (!values.currentTeamId) {
                        return null
                    }

                    const response = await api.get<ChangeRequest>(
                        `api/environments/${values.currentTeamId}/change_requests/${props.id}/`
                    )
                    return response
                },
            },
        ],
    })),
    reducers({
        changeRequestMissing: [
            false,
            {
                loadChangeRequestFailure: () => true,
            },
        ],
        proposedChangesTab: [
            'gated' as ProposedChangesTab,
            {
                setProposedChangesTab: (_, { tab }) => tab,
            },
        ],
    }),
    selectors({
        breadcrumbs: [
            (s) => [s.changeRequest],
            (changeRequest): Breadcrumb[] => [
                {
                    key: Scene.Settings,
                    name: 'Approvals',
                    path: urls.approvals(),
                },
                {
                    key: Scene.Approval,
                    name: changeRequest ? getApprovalActionLabel(changeRequest.action_key) : 'Loading...',
                },
            ],
        ],
    }),
    listeners(({ actions, values, props }) => ({
        approveChangeRequest: async ({ reason }) => {
            try {
                const response = await api.create(
                    `api/environments/${values.currentTeamId}/change_requests/${props.id}/approve/`,
                    { reason: reason || '' }
                )

                // Check if it was auto-applied
                if (response.status === ChangeRequestState.Applied) {
                    lemonToast.success('Change request approved and applied successfully')
                    // Navigate back to approvals list after a short delay
                    setTimeout(() => {
                        router.actions.push(urls.approvals())
                    }, 2000)
                } else if (response.status === ChangeRequestState.Failed) {
                    lemonToast.error(`Approval succeeded but application failed: ${response.message}`)
                    actions.loadChangeRequest()
                } else {
                    lemonToast.success(response.message || 'Change request approved')
                    actions.loadChangeRequest()
                }
            } catch (error: any) {
                lemonToast.error(error.detail || 'Failed to approve change request')
            }
        },
        rejectChangeRequest: async ({ reason }) => {
            try {
                await api.create(`api/environments/${values.currentTeamId}/change_requests/${props.id}/reject/`, {
                    reason,
                })
                lemonToast.success('Change request rejected')
                router.actions.push(urls.approvals())
            } catch (error: any) {
                lemonToast.error(error.detail || 'Failed to reject change request')
            }
        },
        cancelChangeRequest: async ({ reason }) => {
            try {
                await api.create(`api/environments/${values.currentTeamId}/change_requests/${props.id}/cancel/`, {
                    reason,
                })
                lemonToast.success('Change request canceled')
                router.actions.push(urls.approvals())
            } catch (error: any) {
                lemonToast.error(error.detail || 'Failed to cancel change request')
            }
        },
    })),
    urlToAction(({ actions, props }) => ({
        [urls.approval(props.id ?? ':id')]: () => {
            actions.loadChangeRequest()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadChangeRequest()
        actions.loadAllMembers()
        actions.loadRoles()
    }),
])
