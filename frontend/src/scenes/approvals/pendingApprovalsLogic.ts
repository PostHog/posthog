import { afterMount, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, ChangeRequest, ChangeRequestState } from '~/types'

import type { pendingApprovalsLogicType } from './pendingApprovalsLogicType'

export const pendingApprovalsLogic = kea<pendingApprovalsLogicType>([
    path(['scenes', 'approvals', 'pendingApprovalsLogic']),

    loaders(() => ({
        pendingChangeRequests: [
            [] as ChangeRequest[],
            {
                loadPendingChangeRequests: async () => {
                    const currentTeamId = teamLogic.findMounted()?.values.currentTeamId
                    const hasFeature = userLogic.findMounted()?.values.hasAvailableFeature(AvailableFeature.APPROVALS)
                    if (!currentTeamId || !hasFeature) {
                        return []
                    }

                    const response = await api.get(`api/environments/${currentTeamId}/change_requests`, {
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
            (changeRequests): ChangeRequest[] =>
                changeRequests.filter(
                    (cr) =>
                        cr.can_approve &&
                        !cr.user_decision &&
                        (cr.state === ChangeRequestState.Pending || cr.state === ChangeRequestState.Approved)
                ),
        ],
        actionableCount: [(s) => [s.actionableChangeRequests], (actionable): number => actionable.length],
    }),

    afterMount(({ actions }) => {
        actions.loadPendingChangeRequests()
    }),
])
