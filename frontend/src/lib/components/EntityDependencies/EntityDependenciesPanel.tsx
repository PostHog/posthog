import { useValues } from 'kea'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import type { EntityDependencyEntryApi, EntityDependencyGroupApi } from '~/generated/core/api.schemas'
import { ScenePanelLabel } from '~/layout/scenes/SceneLayout'

import { type EntityDependenciesLogicProps, entityDependenciesLogic } from './entityDependenciesLogic'

const GROUP_LABELS: Record<string, string> = {
    cohort: 'Cohorts',
    hog_flow: 'Workflows',
}

const ROLE_LABELS: Record<string, string> = {
    trigger_audience: 'audience',
    trigger_filter: 'trigger filter',
    branch_condition: 'branch condition',
    wait_condition: 'wait condition',
    conversion: 'conversion goal',
}

function roleLabel(role: string): string {
    if (role.startsWith('draft:')) {
        return `${roleLabel(role.slice('draft:'.length))} (draft)`
    }
    return ROLE_LABELS[role] ?? role.replace(/_/g, ' ')
}

function EntityDependencyEntry({ entry }: { entry: EntityDependencyEntryApi }): JSX.Element {
    const { entity, roles } = entry
    const name = entity.name || (entity.status === 'unknown' || entity.status === 'missing' ? entity.id : 'Untitled')
    return (
        <div className="flex items-center gap-1 min-w-0">
            <Tooltip title={roles.length > 0 ? `Used as: ${roles.map(roleLabel).join(', ')}` : undefined}>
                {entity.url ? (
                    <Link to={entity.url} className="truncate" data-attr="entity-dependency-link">
                        {name}
                    </Link>
                ) : (
                    <span className="truncate">{name}</span>
                )}
            </Tooltip>
            {entity.status === 'deleted' && <LemonTag type="danger">Deleted</LemonTag>}
            {entity.status === 'missing' && <LemonTag type="danger">Missing</LemonTag>}
            {entity.status === 'archived' && <LemonTag type="muted">Archived</LemonTag>}
        </div>
    )
}

function EntityDependencyGroup({ group }: { group: EntityDependencyGroupApi }): JSX.Element {
    return (
        <div className="flex flex-col gap-0.5">
            <span className="text-xs text-muted">
                {GROUP_LABELS[group.type] ?? group.type} ({group.total})
            </span>
            {group.results.map((entry) => (
                <EntityDependencyEntry key={entry.entity.id} entry={entry} />
            ))}
            {group.has_more && (
                <span className="text-xs text-muted">
                    Showing {group.results.length} of {group.total}
                </span>
            )}
        </div>
    )
}

export function EntityDependenciesPanel(props: EntityDependenciesLogicProps): JSX.Element {
    const { groups, groupsLoading } = useValues(entityDependenciesLogic(props))
    const title = props.direction === 'used_by' ? 'Used in' : 'Depends on'

    return (
        <ScenePanelLabel title={title}>
            <div className="flex flex-col gap-2 text-sm" data-attr="entity-dependencies-panel">
                {groupsLoading ? (
                    <LemonSkeleton className="h-4 w-full" repeat={2} />
                ) : groups === null ? (
                    <span className="text-muted">Couldn't load references. Refresh the page to try again.</span>
                ) : groups.length === 0 ? (
                    <span className="text-muted">
                        {props.direction === 'used_by' ? 'Not used anywhere yet.' : 'No references to other items.'}
                    </span>
                ) : (
                    groups.map((group) => <EntityDependencyGroup key={group.type} group={group} />)
                )}
            </div>
        </ScenePanelLabel>
    )
}
