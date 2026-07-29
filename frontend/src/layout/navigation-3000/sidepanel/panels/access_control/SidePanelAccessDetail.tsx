import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { WarningHog } from 'lib/components/hedgehogs'
import { teamLogic } from 'scenes/teamLogic'

import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'
import { SidePanelContentContainer } from '../../SidePanelContentContainer'
import { sidePanelStateLogic } from '../../sidePanelStateLogic'
import { AccessControlDetailContent } from './ResourceAccessControlsV2/AccessControlDetail'
import { accessControlsLogic } from './ResourceAccessControlsV2/accessControlsLogic'
import { AccessScope } from './ResourceAccessControlsV2/accessDetailLogic'

/**
 * Access detail for a single member or role, shown in the side panel instead of taking over the
 * settings page. Opened with `openSidePanel(SidePanelTab.AccessDetail, 'member:<id>' | 'role:<id>')`.
 */
export const SidePanelAccessDetail = (): JSX.Element => {
    const { selectedTabOptions } = useValues(sidePanelStateLogic)
    const { currentTeam } = useValues(teamLogic)
    const projectId = `${currentTeam?.id}`

    const [scope, subjectId] = (selectedTabOptions ?? '').split(':')
    const scopeType: AccessScope = scope === 'role' ? 'role' : 'member'

    const logic = accessControlsLogic({ projectId })
    const { membersData, rolesData, membersDataLoading, rolesDataLoading } = useValues(logic)
    const { loadMembers, loadRoles } = useActions(logic)

    // The panel can outlive the settings page that opened it, so make sure the list it reads from is loaded.
    // Deliberately not using the logic's selected member/role — that state drives the settings page's own
    // detail view, and setting it here would open both at once.
    useEffect(() => {
        if (scopeType === 'role') {
            if (!rolesData && !rolesDataLoading) {
                loadRoles()
            }
        } else if (!membersData && !membersDataLoading) {
            loadMembers()
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [scopeType, membersData, rolesData])

    const entry =
        scopeType === 'role'
            ? (rolesData?.results.find((r) => r.role_id === subjectId) ?? null)
            : (membersData?.results.find((m) => m.organization_membership_id === subjectId) ?? null)
    const loading = scopeType === 'role' ? rolesDataLoading : membersDataLoading

    return (
        <div className="flex flex-col overflow-hidden grow">
            <SidePanelContentContainer>
                <SidePanelPaneHeader title="Access control" />
                {!subjectId ? (
                    <div className="mx-auto p-8 max-w-160 mt-8 text-center">
                        <div className="max-w-24 mx-auto">
                            <WarningHog className="w-full h-full" />
                        </div>
                        <h2>Nothing selected</h2>
                        <p>Select a specific member or role to view and edit their access permissions.</p>
                    </div>
                ) : (
                    <div className="px-3 py-2 space-y-6">
                        {entry ? (
                            <AccessControlDetailContent projectId={projectId} scopeType={scopeType} entry={entry} />
                        ) : loading ? (
                            <LemonSkeleton className="h-24 w-full" />
                        ) : (
                            <p className="text-secondary">{scopeType === 'role' ? 'Role' : 'Member'} not found.</p>
                        )}
                    </div>
                )}
            </SidePanelContentContainer>
        </div>
    )
}
