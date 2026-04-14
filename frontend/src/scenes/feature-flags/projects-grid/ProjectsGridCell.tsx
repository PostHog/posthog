import { IconLock } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'

import { OrganizationFeatureFlag } from '~/types'

import { groupFilters } from '../FeatureFlags'

export type CellState =
    | { kind: 'loading' }
    | { kind: 'missing' }
    | { kind: 'no-access' }
    | { kind: 'present'; sibling: OrganizationFeatureFlag }

export function ProjectsGridCell({ state }: { state: CellState }): JSX.Element {
    if (state.kind === 'loading') {
        return <div className="h-10 w-full rounded bg-bg-3000 animate-pulse" data-attr="projects-grid-cell-loading" />
    }
    if (state.kind === 'missing') {
        return (
            <span className="text-secondary text-xs" data-attr="projects-grid-cell-missing">
                Not in this project
            </span>
        )
    }
    if (state.kind === 'no-access') {
        return (
            <Tooltip title="You don't have access to feature flags in this project.">
                <span
                    className="inline-flex items-center gap-1 text-secondary text-xs"
                    data-attr="projects-grid-cell-no-access"
                >
                    <IconLock /> No access
                </span>
            </Tooltip>
        )
    }

    const { sibling } = state
    const status = sibling.active ? 'Enabled' : 'Disabled'
    const rollout = groupFilters(sibling.filters, true)
    const evals = sibling.evaluations_7d_available ? (sibling.evaluations_7d ?? 0).toLocaleString() : '—'

    return (
        <Link
            to={`/project/${sibling.team_id}/feature_flags/${sibling.flag_id}`}
            className="block hover:bg-bg-3000 rounded px-2 py-1"
            data-attr="projects-grid-cell-present"
        >
            <LemonTag type={sibling.active ? 'success' : 'default'} className="uppercase">
                {status}
            </LemonTag>
            <div className="text-xs text-secondary mt-1 truncate">{rollout}</div>
            <div className="text-xs text-secondary mt-0.5">{evals} evals · 7d</div>
        </Link>
    )
}
