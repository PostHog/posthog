import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { ApprovalPolicy } from '~/types'

import { FEATURE_FLAGS } from '../constants'
import type { approvalsGateLogicType } from './approvalsGateLogicType'

export const approvalsGateLogic = kea<approvalsGateLogicType>([
    path(['lib', 'approvals', 'approvalsGateLogic']),

    connect({
        values: [featureFlagLogic, ['featureFlags']],
    }),

    loaders(({ values }) => ({
        activePolicies: [
            [] as ApprovalPolicy[],
            {
                loadActivePolicies: async () => {
                    // Don't load if FF is disabled
                    if (!values.featureFlags[FEATURE_FLAGS.APPROVALS]) {
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
            (s) => [s.featureFlags],
            (featureFlags: Record<string, boolean | string>): boolean => !!featureFlags[FEATURE_FLAGS.APPROVALS],
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
