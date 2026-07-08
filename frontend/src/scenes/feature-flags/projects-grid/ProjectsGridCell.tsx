import { IconLock } from '@posthog/icons'
import { LemonSkeleton, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { OrganizationFeatureFlag } from '~/types'

import { groupFilters } from '../FeatureFlags'
import { FlagActiveToggleTag } from '../FlagActiveToggleTag'

export type CellState =
    | { kind: 'loading' }
    | { kind: 'missing' }
    | { kind: 'no-access' }
    | { kind: 'present'; sibling: OrganizationFeatureFlag }

export function ProjectsGridCell({
    state,
    onToggle,
    toggling,
}: {
    state: CellState
    onToggle?: (active: boolean) => void
    toggling?: boolean
}): JSX.Element {
    if (state.kind === 'loading') {
        return <LemonSkeleton className="h-6 w-24" data-attr="projects-grid-cell-loading" />
    }
    if (state.kind === 'missing') {
        return (
            <LemonTag type="default" className="uppercase" data-attr="projects-grid-cell-missing">
                Not in this project
            </LemonTag>
        )
    }
    if (state.kind === 'no-access') {
        return (
            <Tooltip title="You don't have access to feature flags in this project.">
                <LemonTag
                    type="default"
                    icon={<IconLock />}
                    className="uppercase"
                    data-attr="projects-grid-cell-no-access"
                >
                    No access
                </LemonTag>
            </Tooltip>
        )
    }

    const { sibling } = state
    const rollout = groupFilters(sibling.filters, true)
    const evals = typeof sibling.evaluations_7d === 'number' ? sibling.evaluations_7d.toLocaleString() : '—'

    return (
        <div className="flex flex-col items-start py-1">
            <FlagActiveToggleTag
                active={sibling.active}
                toggling={toggling}
                onToggle={onToggle}
                data-attr="projects-grid-cell-toggle"
            />
            <Link
                subtle
                to={`/project/${sibling.team_id}/feature_flags/${sibling.flag_id}`}
                className="text-xs text-tertiary mt-1"
            >
                <span data-attr="projects-grid-cell-present">
                    {rollout} · {evals} evals · 7d
                </span>
            </Link>
        </div>
    )
}
