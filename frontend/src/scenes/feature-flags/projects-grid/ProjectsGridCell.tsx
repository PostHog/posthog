import { IconLock } from '@posthog/icons'
import { LemonSkeleton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'

import { OrganizationFeatureFlag } from '~/types'

import { groupFilters } from '../FeatureFlags'

export type CellState =
    | { kind: 'loading' }
    | { kind: 'missing' }
    | { kind: 'no-access' }
    | { kind: 'present'; sibling: OrganizationFeatureFlag }

export function ProjectsGridCell({ state }: { state: CellState }): JSX.Element {
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
        <LemonTableLink
            to={`/project/${sibling.team_id}/feature_flags/${sibling.flag_id}`}
            title={
                <LemonTag type={sibling.active ? 'success' : 'default'} className="uppercase">
                    {sibling.active ? 'Enabled' : 'Disabled'}
                </LemonTag>
            }
            description={
                <span data-attr="projects-grid-cell-present">
                    {rollout} · {evals} evals · 7d
                </span>
            }
        />
    )
}
