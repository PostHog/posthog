import { useValues } from 'kea'

import { IconLock } from '@posthog/icons'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle, Skeleton } from '@posthog/quill'

import { teamLogic } from 'scenes/teamLogic'

import { accessControlsLogic } from '../ResourceAccessControlsV2/accessControlsLogic'
import type { AccessDetailSubject } from '../ResourceAccessControlsV2/accessDetailLogic'
import { QuillAccessControlDetail } from '../ResourceAccessControlsV2/QuillAccessControlDetail'

function PanelSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col gap-4 p-4">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-24 w-full" />
        </div>
    )
}

export function QuillAccessDetailPanel(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    // Mounting accessControlsLogic before the team loads would key it on "undefined" and fire requests at
    // api/projects/undefined/...
    if (!currentTeam) {
        return <PanelSkeleton />
    }
    return <QuillAccessDetailForProject projectId={`${currentTeam.id}`} />
}

function emptyStateCopy(subject: AccessDetailSubject | null): { title: string; description: string } {
    if (!subject) {
        return {
            title: 'Nothing selected',
            description: 'Select a member or role to view and edit their access permissions.',
        }
    }
    const noun = subject.scopeType === 'role' ? 'role' : 'member'
    return {
        title: noun === 'role' ? 'Role not found' : 'Member not found',
        description: `This ${noun} may have been removed, or you may not have access to it. Pick another from the list.`,
    }
}

function QuillAccessDetailForProject({ projectId }: { projectId: string }): JSX.Element {
    const { panelEntry, panelEntryLoading, activePanelSubject } = useValues(accessControlsLogic({ projectId }))

    if (!activePanelSubject || !panelEntry) {
        if (activePanelSubject && panelEntryLoading) {
            return <PanelSkeleton />
        }
        const { title, description } = emptyStateCopy(activePanelSubject)
        return (
            <Empty className="flex-1">
                <EmptyHeader>
                    <EmptyMedia variant="icon">
                        <IconLock />
                    </EmptyMedia>
                    <EmptyTitle>{title}</EmptyTitle>
                    <EmptyDescription>{description}</EmptyDescription>
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
