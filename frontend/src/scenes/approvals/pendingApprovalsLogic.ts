import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, ChangeRequest } from '~/types'

import type { pendingApprovalsLogicType } from './pendingApprovalsLogicType'

export const pendingApprovalsLogic = kea<pendingApprovalsLogicType>([
    path(['scenes', 'approvals', 'pendingApprovalsLogic']),

    connect(() => ({
        values: [teamLogic, ['currentTeamId'], userLogic, ['hasAvailableFeature']],
    })),

    loaders(({ values }) => ({
        pendingChangeRequests: [
            [] as ChangeRequest[],
            {
                loadPendingChangeRequests: async () => {
                    if (!values.currentTeamId || !values.hasAvailableFeature(AvailableFeature.APPROVALS)) {
                        return []
                    }

                    const response = await api.get(`api/environments/${values.currentTeamId}/change_requests`, {
                        state: 'pending,approved',
                    })
                    return response.results || []
                },
            },
        ],
    })),

    selectors({
        actionableChangeRequests: [
            (s) => [s.pendingChangeRequests],
            (changeRequests): ChangeRequest[] => changeRequests.filter((cr) => cr.can_approve && !cr.user_decision),
        ],
        actionableCount: [(s) => [s.actionableChangeRequests], (actionable): number => actionable.length],
    }),

    afterMount(({ actions }) => {
        actions.loadPendingChangeRequests()
    }),
])
