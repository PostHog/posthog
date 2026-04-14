import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { projectsGridLogic } from './projectsGridLogic'
import { ProjectsGridRow } from './ProjectsGridRow'
import { ProjectsGridToolbar } from './ProjectsGridToolbar'

export function ProjectsGrid(): JSX.Element {
    const {
        flags,
        flagsPageLoading,
        flagsHasMore,
        visibleColumns,
        accessibleTeamIds,
        siblingsByFlagKey,
        siblingsLoadingKeys,
    } = useValues(projectsGridLogic)
    const { loadMoreFlags } = useActions(projectsGridLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { currentTeamId } = useValues(teamLogic)

    const sentinelRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        const el = sentinelRef.current
        if (!el) {
            return
        }
        const io = new IntersectionObserver(
            (entries) => {
                if (entries[0]?.isIntersecting && flagsHasMore && !flagsPageLoading) {
                    loadMoreFlags()
                }
            },
            { rootMargin: '400px' }
        )
        io.observe(el)
        return () => io.disconnect()
    }, [flagsHasMore, flagsPageLoading, loadMoreFlags])

    if (!currentTeamId) {
        return <LemonSkeleton className="h-40" />
    }

    const teamsById = new Map((currentOrganization?.teams ?? []).map((t) => [t.id, t]))

    return (
        <div>
            <ProjectsGridToolbar />
            <div className="overflow-x-auto">
                <table className="w-full">
                    <thead>
                        <tr className="text-xs uppercase text-secondary">
                            <th className="text-left p-2">Flag</th>
                            {visibleColumns.map((teamId) => (
                                <th key={teamId} className="text-left p-2 min-w-[180px]">
                                    {teamsById.get(teamId)?.name ?? `Project ${teamId}`}
                                    {teamId === currentTeamId && (
                                        <span className="ml-1 text-secondary font-normal">(current)</span>
                                    )}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {flags.map((flag) => (
                            <ProjectsGridRow
                                key={flag.id}
                                flag={flag}
                                visibleColumns={visibleColumns}
                                currentTeamId={currentTeamId}
                                accessibleTeamIds={accessibleTeamIds}
                                siblings={siblingsByFlagKey[flag.key]}
                                siblingsLoading={siblingsLoadingKeys.includes(flag.key)}
                            />
                        ))}
                    </tbody>
                </table>
                {flags.length === 0 && !flagsPageLoading && (
                    <div className="text-center text-secondary py-8">No flags match your search.</div>
                )}
                {flagsPageLoading && <LemonSkeleton className="h-10 my-2" />}
                <div ref={sentinelRef} className="h-1" />
            </div>
        </div>
    )
}

export default ProjectsGrid
