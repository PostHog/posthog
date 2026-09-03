import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { WarningHog } from 'lib/components/hedgehogs'
import { teamLogic } from 'scenes/teamLogic'

import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'
import { SidePanelContentContainer } from '../../SidePanelContentContainer'
import { AccessControlDetailContent } from './ResourceAccessControlsV2/AccessControlDetail'
import { accessControlsLogic } from './ResourceAccessControlsV2/accessControlsLogic'
import type { AccessDetailSubjectScope } from './ResourceAccessControlsV2/accessDetailLogic'

/**
 * Access detail for a single member or role, shown in the side panel instead of taking over the
 * settings page. Opened with `openSidePanel(SidePanelTab.AccessDetail, 'member:<id>' | 'role:<id>')`.
 * Which subject to show, and loading the member/role lists it reads from, live in accessControlsLogic
 * (`activePanelSubject`) — this component only renders.
 */
export const SidePanelAccessDetail = (): JSX.Element => {
    const { currentTeam } = useValues(teamLogic)

    // Mounting accessControlsLogic before the team loads would key it on "undefined" and fire
    // requests at api/projects/undefined/...
    if (!currentTeam) {
        return (
            <div className="flex flex-col overflow-hidden grow">
                <SidePanelContentContainer>
                    <SidePanelPaneHeader title="Access control" />
                    <div className="px-3 py-2">
                        <LemonSkeleton className="h-24 w-full" />
                    </div>
                </SidePanelContentContainer>
            </div>
        )
    }
    return <SidePanelAccessDetailForProject projectId={`${currentTeam.id}`} />
}

function SidePanelAccessDetailForProject({ projectId }: { projectId: string }): JSX.Element {
    const logic = accessControlsLogic({ projectId })
    const { panelEntry, panelEntryLoading, activePanelSubject } = useValues(logic)

    const scopeType: AccessDetailSubjectScope = activePanelSubject?.scopeType ?? 'member'
    const subjectId = activePanelSubject?.subjectId

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
                        {panelEntry ? (
                            <AccessControlDetailContent
                                projectId={projectId}
                                scopeType={scopeType}
                                entry={panelEntry}
                            />
                        ) : panelEntryLoading ? (
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
