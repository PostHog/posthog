import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { toParams } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, ChangeRequest, ChangeRequestState } from '~/types'

import type { pendingApprovalsLogicType } from './pendingApprovalsLogicType'

export const pendingApprovalsLogic = kea<pendingApprovalsLogicType>([
    path(['scenes', 'approvals', 'pendingApprovalsLogic']),

    connect(() => ({
        values: [teamLogic, ['currentTeamId'], userLogic, ['hasAvailableFeature']],
    })),

    loaders(({ values }) => ({
        // Fetches both pending and approved-but-not-yet-applied CRs
        unresolvedChangeRequests: [
            [] as ChangeRequest[],
            {
                loadUnresolvedChangeRequests: async () => {
                    if (!values.currentTeamId || !values.hasAvailableFeature(AvailableFeature.APPROVALS)) {
                        return []
                    }

                    const response = await api.get(
                        `api/environments/${values.currentTeamId}/change_requests?${toParams({ state: 'pending,approved' })}`
                    )
                    return response.results || []
                },
            },
        ],
    })),

    selectors({
        actionableChangeRequests: [
            (s) => [s.unresolvedChangeRequests],
            (changeRequests): ChangeRequest[] =>
                changeRequests.filter(
                    (cr) => cr.state === ChangeRequestState.Pending && cr.can_approve && !cr.user_decision
                ),
        ],
        actionableCount: [(s) => [s.actionableChangeRequests], (actionable): number => actionable.length],
        unresolvedCount: [(s) => [s.unresolvedChangeRequests], (unresolved): number => unresolved.length],
    }),

    afterMount(({ actions }) => {
        actions.loadUnresolvedChangeRequests()
    }),
])
