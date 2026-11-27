import { useValues } from 'kea'

import { IconLock } from '@posthog/icons'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle, Skeleton } from '@posthog/quill'

import { teamLogic } from 'scenes/teamLogic'

import { accessControlsLogic } from '../ResourceAccessControlsV2/accessControlsLogic'
import { QuillAccessControlDetail } from '../ResourceAccessControlsV2/QuillAccessControlDetail'

function PanelSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col gap-4 p-4">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-24 w-full" />
        </div>
    )
}

/**
 * The access detail of one member or role, opened with `openSidePanel(SidePanelTab.AccessDetail, 'member:<id>' |
 * 'role:<id>')`. Which subject to show lives in accessControlsLogic (`activePanelSubject`).
 */
export function QuillAccessDetailPanel(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    // Mounting accessControlsLogic before the team loads would key it on "undefined" and fire requests at
    // api/projects/undefined/...
    if (!currentTeam) {
        return <PanelSkeleton />
    }
    return <QuillAccessDetailForProject projectId={`${currentTeam.id}`} />
}

function QuillAccessDetailForProject({ projectId }: { projectId: string }): JSX.Element {
    const { panelEntry, panelEntryLoading, activePanelSubject } = useValues(accessControlsLogic({ projectId }))

    if (!activePanelSubject) {
        return (
            <Empty className="flex-1">
                <EmptyHeader>
                    <EmptyMedia variant="icon">
                        <IconLock />
                    </EmptyMedia>
                    <EmptyTitle>Nothing selected</EmptyTitle>
                    <EmptyDescription>
                        Select a member or role to view and edit their access permissions.
                    </EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }

    if (!panelEntry) {
        if (panelEntryLoading) {
            return <PanelSkeleton />
        }
        const noun = activePanelSubject.scopeType === 'role' ? 'role' : 'member'
        return (
            <Empty className="flex-1">
                <EmptyHeader>
                    <EmptyMedia variant="icon">
                        <IconLock />
                    </EmptyMedia>
                    <EmptyTitle>{noun === 'role' ? 'Role not found' : 'Member not found'}</EmptyTitle>
                    <EmptyDescription>
                        {`This ${noun} may have been removed, or you may not have access to it. Pick another from the list.`}
                    </EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }

    return (
        <div className="min-h-0 flex-1 overflow-y-auto scroll-mask-y-4 scroll-py-4">
            <div className="flex flex-col p-4">
                <QuillAccessControlDetail
                    projectId={projectId}
                    scopeType={activePanelSubject.scopeType}
                    entry={panelEntry}
                />
            </div>
        </div>
    )
}
