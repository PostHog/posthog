import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { ApprovalPolicy } from '~/types'

import type { approvalPoliciesLogicType } from './approvalPoliciesLogicType'

export const approvalPoliciesLogic = kea<approvalPoliciesLogicType>([
    path(['scenes', 'settings', 'organization', 'Approvals', 'approvalPoliciesLogic']),
    actions({
        loadPolicies: true,
        createPolicy: (policy: Partial<ApprovalPolicy>) => ({ policy }),
        updatePolicy: (id: string, policy: Partial<ApprovalPolicy>) => ({ id, policy }),
        deletePolicy: (id: string) => ({ id }),
    }),
    loaders(() => ({
        policies: [
            [] as ApprovalPolicy[],
            {
                loadPolicies: async () => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return []
                    }
                    const response = await api.get<{ results: ApprovalPolicy[] }>(
                        `api/environments/${teamId}/approval_policies/`
                    )
                    return response.results || []
                },
            },
        ],
    })),
    reducers({
        policies: {
            createPolicy: (state, { policy }) => [...state, policy as ApprovalPolicy],
            updatePolicy: (state, { id, policy }) =>
                state.map((p) => (p.id === id ? { ...p, ...policy } : p)) as ApprovalPolicy[],
            deletePolicy: (state, { id }) => state.filter((p) => p.id !== id),
        },
    }),
    listeners(({ actions }) => ({
        createPolicy: async ({ policy }) => {
            try {
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    throw new Error('No team selected')
                }
                await api.create(`api/environments/${teamId}/approval_policies/`, policy)
                lemonToast.success('Approval policy created')
                actions.loadPolicies()
            } catch (error: any) {
                lemonToast.error(error.detail || 'Failed to create approval policy')
            }
        },
        updatePolicy: async ({ id, policy }) => {
            try {
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    throw new Error('No team selected')
                }
                await api.update(`api/environments/${teamId}/approval_policies/${id}/`, policy)
                lemonToast.success('Approval policy updated')
                actions.loadPolicies()
            } catch (error: any) {
                lemonToast.error(error.detail || 'Failed to update approval policy')
            }
        },
        deletePolicy: async ({ id }) => {
            try {
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    throw new Error('No team selected')
                }
                await api.delete(`api/environments/${teamId}/approval_policies/${id}/`)
                lemonToast.success('Approval policy deleted')
                actions.loadPolicies()
            } catch (error: any) {
                lemonToast.error(error.detail || 'Failed to delete approval policy')
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadPolicies()
    }),
])
