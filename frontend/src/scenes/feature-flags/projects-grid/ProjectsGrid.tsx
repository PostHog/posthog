import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { OrganizationFeatureFlag } from '~/types'

import { CellState, ProjectsGridCell } from './ProjectsGridCell'
import { ProjectsGridRow, projectsGridLogic } from './projectsGridLogic'
import { ProjectsGridToolbar } from './ProjectsGridToolbar'

function cellStateFor(
    row: ProjectsGridRow,
    teamId: number,
    accessibleTeamIds: Set<number>,
    siblings: OrganizationFeatureFlag[] | undefined,
    siblingsLoading: boolean
): CellState {
    const siblingForTeam = siblings?.find((s) => s.team_id === teamId)
    if (siblingForTeam) {
        return { kind: 'present', sibling: siblingForTeam }
    }

    // Before siblings load, render the representative project's cell directly so it doesn't flash
    // a skeleton (eval count is unavailable until siblings arrive).
    if (teamId === row.team_id) {
        return {
            kind: 'present',
            sibling: {
                flag_id: row.flag_id,
                team_id: teamId,
                created_by: null,
                filters: row.filters,
                created_at: '',
                active: row.active,
            },
        }
    }

    if (siblingsLoading || siblings === undefined) {
        return { kind: 'loading' }
    }
    if (!accessibleTeamIds.has(teamId)) {
        return { kind: 'no-access' }
    }
    return { kind: 'missing' }
}

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

    const teamsById = useMemo(
        () => new Map((currentOrganization?.teams ?? []).map((t) => [t.id, t])),
        [currentOrganization?.teams]
    )

    if (!currentTeamId) {
        return <LemonSkeleton className="h-40" />
    }

    const columnWidth = `${100 / (visibleColumns.length + 1)}%`

    const columns: LemonTableColumns<ProjectsGridRow> = [
        {
            title: 'Flag',
            key: 'flag',
            width: columnWidth,
            render: (_, row) => (
                <LemonTableLink
                    to={`/project/${row.team_id}/feature_flags/${row.flag_id}`}
                    title={row.name || row.key}
                    description={row.key}
                />
            ),
        },
        ...visibleColumns.map((teamId) => ({
            title: (
                <span>
                    {teamsById.get(teamId)?.name ?? `Project ${teamId}`}
                    {teamId === currentTeamId && (
                        <span className="ml-1 text-tertiary font-normal normal-case">(current)</span>
                    )}
                </span>
            ),
            key: `project-${teamId}`,
            width: columnWidth,
            render: (_: unknown, row: ProjectsGridRow) => (
                <ProjectsGridCell
                    state={cellStateFor(
                        row,
                        teamId,
                        accessibleTeamIds,
                        siblingsByFlagKey[row.key],
                        siblingsLoadingKeys.includes(row.key)
                    )}
                />
            ),
        })),
    ]

    return (
        <SceneSection
            title="Feature flags across projects"
            description="Compare each flag's status, rollout, and recent usage across your organization's projects."
        >
            <ProjectsGridToolbar />
            <LemonTable
                columns={columns}
                dataSource={flags}
                rowKey="key"
                loading={flagsPageLoading && flags.length === 0}
                emptyState="No flags match your search."
                data-attr="projects-grid-table"
                className="[&_table]:table-fixed"
            />
            {flagsPageLoading && flags.length > 0 && <LemonSkeleton className="h-8 my-2" />}
            <div ref={sentinelRef} className="h-1" />
        </SceneSection>
    )
}

export default ProjectsGrid
