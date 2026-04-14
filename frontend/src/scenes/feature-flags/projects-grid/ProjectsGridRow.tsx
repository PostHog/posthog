import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { FeatureFlagType, OrganizationFeatureFlag } from '~/types'

import { CellState, ProjectsGridCell } from './ProjectsGridCell'

interface Props {
    flag: FeatureFlagType
    visibleColumns: number[]
    currentTeamId: number
    accessibleTeamIds: Set<number>
    siblings: OrganizationFeatureFlag[] | undefined
    siblingsLoading: boolean
}

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

export function ProjectsGridRow({
    flag,
    visibleColumns,
    currentTeamId,
    accessibleTeamIds,
    siblings,
    siblingsLoading,
}: Props): JSX.Element {
    return (
        <tr data-attr="projects-grid-row" className="border-b border-border">
            <td className="p-2 align-top min-w-[200px]">
                <Link to={urls.featureFlag(flag.id as number)} className="font-medium">
                    {flag.name || flag.key}
                </Link>
                <div className="text-xs text-secondary truncate">{flag.key}</div>
            </td>
            {visibleColumns.map((teamId) => (
                <td key={teamId} className="p-2 align-top min-w-[180px]">
                    <ProjectsGridCell
                        state={cellStateFor(flag, teamId, currentTeamId, accessibleTeamIds, siblings, siblingsLoading)}
                    />
                </td>
            ))}
        </tr>
    )
}
