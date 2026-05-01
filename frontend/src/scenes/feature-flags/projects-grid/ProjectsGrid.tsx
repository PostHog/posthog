import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { FeatureFlagType, OrganizationFeatureFlag } from '~/types'

import { CellState, ProjectsGridCell } from './ProjectsGridCell'
import { projectsGridLogic } from './projectsGridLogic'
import { ProjectsGridToolbar } from './ProjectsGridToolbar'

function cellStateFor(
    flag: FeatureFlagType,
    teamId: number,
    currentTeamId: number,
    accessibleTeamIds: Set<number>,
    siblings: OrganizationFeatureFlag[] | undefined,
    siblingsLoading: boolean
): CellState {
    const siblingForTeam = siblings?.find((s) => s.team_id === teamId)
    if (siblingForTeam) {
        return { kind: 'present', sibling: siblingForTeam }
    }

    // Before siblings load, render the current team's cell from the flag directly
    // (eval count unavailable until siblings arrive).
    if (teamId === currentTeamId) {
        return {
            kind: 'present',
            sibling: {
                flag_id: flag.id,
                team_id: teamId,
                created_by: flag.created_by ?? null,
                filters: flag.filters,
                created_at: flag.created_at ?? '',
                active: flag.active,
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

    const columns: LemonTableColumns<FeatureFlagType> = [
        {
            title: 'Flag',
            key: 'flag',
            width: columnWidth,
            render: (_, flag) => (
                <LemonTableLink
                    to={urls.featureFlag(flag.id as number)}
                    title={flag.name || flag.key}
                    description={flag.key}
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
            render: (_: unknown, flag: FeatureFlagType) => (
                <ProjectsGridCell
                    state={cellStateFor(
                        flag,
                        teamId,
                        currentTeamId,
                        accessibleTeamIds,
                        siblingsByFlagKey[flag.key],
                        siblingsLoadingKeys.includes(flag.key)
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
                rowKey="id"
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
