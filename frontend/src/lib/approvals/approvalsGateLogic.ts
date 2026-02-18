import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { userLogic } from 'scenes/userLogic'

import { ApprovalPolicy, AvailableFeature } from '~/types'

import type { approvalsGateLogicType } from './approvalsGateLogicType'

export const approvalsGateLogic = kea<approvalsGateLogicType>([
    path(['lib', 'approvals', 'approvalsGateLogic']),

    connect(() => ({
        values: [userLogic, ['hasAvailableFeature']],
    })),

    loaders(({ values }) => ({
        activePolicies: [
            [] as ApprovalPolicy[],
            {
                loadActivePolicies: async () => {
                    if (!values.hasAvailableFeature(AvailableFeature.APPROVALS)) {
                        return []
                    }

                    try {
                        const response = await api.get('api/environments/@current/approval_policies/')
                        return (response.results || []).filter((p: ApprovalPolicy) => p.enabled)
                    } catch {
                        return []
                    }
                },
            },
        ],
    })),

    selectors({
        isApprovalsFeatureEnabled: [
            (s) => [s.hasAvailableFeature],
            (hasAvailableFeature): boolean => hasAvailableFeature(AvailableFeature.APPROVALS),
        ],

        isApprovalRequired: [
            (s) => [s.isApprovalsFeatureEnabled, s.activePolicies],
            (isEnabled: boolean, policies: ApprovalPolicy[]) =>
                (actionKey: string): boolean => {
                    if (!isEnabled) {
                        return false
                    }
                    return policies.some((p: ApprovalPolicy) => p.action_key === actionKey && p.enabled)
                },
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadActivePolicies()
    }),
])
