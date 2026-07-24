import { useActions, useValues } from 'kea'

import { IconInfo, IconPencil, IconPlus, IconRefresh, IconTrash } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns, Tooltip } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TZLabel } from 'lib/components/TZLabel'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'

import type {
    CustomPropertyDefinitionApi,
    CustomPropertySyncRunApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { CustomPropertyTargetType, customPropertyDefinitionsLogic } from './customPropertyDefinitionsLogic'
import { CustomPropertyModal } from './CustomPropertyModal'
import { type SourceSyncStatusLevel, sourceSyncStatus } from './customPropertyTypes'

const TAG_TYPE_BY_SYNC_LEVEL: Record<SourceSyncStatusLevel, LemonTagType> = {
    synced: 'success',
    error: 'danger',
    disabled: 'muted',
    pending: 'default',
}

const TAG_TYPE_BY_RUN_STATUS: Record<string, LemonTagType> = {
    completed: 'success',
    running: 'primary',
    failed: 'danger',
}

// Labels that differ between the person- and group-target views of the same warehouse-sync machinery.
type ProfileLabels = { entity: string; entityPlural: string; keyColumn: string }
const LABELS_BY_TARGET: Record<'person' | 'group', ProfileLabels> = {
    person: { entity: 'person', entityPlural: 'people', keyColumn: 'Distinct ID column' },
    group: { entity: 'group', entityPlural: 'groups', keyColumn: 'Group key column' },
}

// Run history for one source, loaded lazily when its row is expanded.
function ProfilePropertyRuns({ sourceId, labels }: { sourceId: string; labels: ProfileLabels }): JSX.Element {
    const { runsBySourceId, runsLoadingBySourceId } = useValues(customPropertyDefinitionsLogic)
    const runs = runsBySourceId[sourceId] ?? []

    const columns: LemonTableColumns<CustomPropertySyncRunApi> = [
        {
            title: 'Status',
            render: (_, run) => (
                <Tooltip title={run.error ?? undefined}>
                    <LemonTag type={TAG_TYPE_BY_RUN_STATUS[run.status] ?? 'default'}>{run.status}</LemonTag>
                </Tooltip>
            ),
        },
        { title: 'Trigger', dataIndex: 'trigger' },
        { title: 'Rows produced', render: (_, run) => run.produced },
        { title: `Affected ${labels.entityPlural}`, render: (_, run) => run.existing },
        {
            title: `Skipped (no ${labels.entity})`,
            render: (_, run) => <span className="text-secondary">{run.skipped_missing_person}</span>,
        },
        {
            title: 'Started',
            render: (_, run) =>
                run.started_at ? <TZLabel time={run.started_at} /> : <span className="text-secondary">—</span>,
        },
        {
            title: 'Finished',
            render: (_, run) =>
                run.finished_at ? <TZLabel time={run.finished_at} /> : <span className="text-secondary">—</span>,
        },
    ]

    return (
        <LemonTable
            columns={columns}
            dataSource={runs}
            loading={runsLoadingBySourceId[sourceId] ?? false}
            rowKey="id"
            size="small"
            emptyState="No runs yet."
        />
    )
}

// First-class Customer analytics view of the warehouse → person/group property sources: manages the
// column mappings, shows the next scheduled sync, lets you trigger a sync or backfill, and expands to
// run history. Parametrized by target so the person and group settings entries share one implementation.
function WarehouseProfilePropertiesSetting({ targetType }: { targetType: 'person' | 'group' }): JSX.Element {
    const { definitions, definitionsLoading, triggeringSourceIds } = useValues(customPropertyDefinitionsLogic)
    const { openCreateModal, openEditModal, deleteDefinition, triggerSync, triggerBackfill, loadRuns } =
        useActions(customPropertyDefinitionsLogic)
    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const labels = LABELS_BY_TARGET[targetType]
    const profileDefinitions = definitions.filter((definition) => definition.target_type === targetType)

    const confirmDelete = (definition: CustomPropertyDefinitionApi): void => {
        LemonDialog.open({
            title: `Delete ${definition.name}?`,
            description: `This stops syncing its warehouse columns onto ${labels.entityPlural}. Values already synced stay on the ${labels.entityPlural}, but they'll stop updating. This can't be undone.`,
            primaryButton: {
                children: 'Delete',
                status: 'danger',
                onClick: () => deleteDefinition({ id: definition.id }),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    const columns: LemonTableColumns<CustomPropertyDefinitionApi> = [
        {
            title: 'Name',
            dataIndex: 'name',
            render: (_, definition) => <span className="font-semibold">{definition.name}</span>,
        },
        {
            title: labels.keyColumn,
            render: (_, definition) =>
                definition.source?.key_column ? (
                    <code>{definition.source.key_column}</code>
                ) : (
                    <span className="text-secondary">—</span>
                ),
        },
        {
            title: 'Mapped properties',
            render: (_, definition) => {
                const map = (definition.source?.column_property_map ?? {}) as Record<string, string>
                const entries = Object.entries(map)
                if (!entries.length) {
                    return <span className="text-secondary">—</span>
                }
                return (
                    <div className="flex flex-wrap gap-1">
                        {entries.map(([column, property]) => (
                            <LemonTag key={column} type="option">
                                {column} → {property}
                            </LemonTag>
                        ))}
                    </div>
                )
            },
        },
        {
            title: 'Sync',
            render: (_, definition) => {
                if (!definition.source) {
                    return <span className="text-secondary">—</span>
                }
                const status = sourceSyncStatus(definition.source)
                // Only report an affected count for a finished run — an in-progress/failed run's count
                // isn't "the last run". status.tooltip is undefined for the synced/pending states, so
                // build the title from the present parts rather than interpolating undefined into it.
                const latestRun = definition.source.latest_run
                const affected = latestRun?.status === 'completed' ? latestRun.existing : undefined
                const tooltipTitle =
                    [
                        status.tooltip,
                        affected != null ? `${affected} ${labels.entityPlural} affected on the last run` : null,
                    ]
                        .filter(Boolean)
                        .join(' — ') || undefined
                return (
                    <Tooltip title={tooltipTitle}>
                        <span className="flex items-center gap-2">
                            <LemonTag type={TAG_TYPE_BY_SYNC_LEVEL[status.level]}>{status.label}</LemonTag>
                            {status.level === 'synced' && definition.source.last_synced_at && (
                                <TZLabel time={definition.source.last_synced_at} className="text-secondary" />
                            )}
                            {affected != null && <IconInfo className="text-secondary" />}
                        </span>
                    </Tooltip>
                )
            },
        },
        {
            title: 'Next sync',
            render: (_, definition) =>
                definition.source?.next_sync_at ? (
                    <TZLabel time={definition.source.next_sync_at} className="text-secondary" />
                ) : (
                    <span className="text-secondary">—</span>
                ),
        },
        {
            title: '',
            width: 0,
            render: (_, definition) => {
                const source = definition.source
                const triggering = !!source && triggeringSourceIds.includes(source.id)
                const running = source?.latest_run?.status === 'running'
                // A run is in flight for this table; block a second trigger and show it as busy.
                const busyReason = running ? 'A sync or backfill is already running for this table' : undefined
                const disabledReason = restrictionReason ?? (!source ? 'No source configured' : undefined) ?? busyReason
                return (
                    <div className="flex gap-1 justify-end">
                        <LemonButton
                            size="small"
                            icon={<IconRefresh />}
                            tooltip="Sync now — re-runs the warehouse sync for this table"
                            onClick={() => source && triggerSync({ sourceId: source.id })}
                            loading={triggering}
                            disabledReason={disabledReason}
                        />
                        <LemonButton
                            size="small"
                            tooltip="Backfill — reads the whole table to fill in historical rows"
                            onClick={() => source && triggerBackfill({ sourceId: source.id })}
                            loading={triggering || running}
                            disabledReason={disabledReason}
                        >
                            Backfill
                        </LemonButton>
                        <LemonButton
                            size="small"
                            icon={<IconPencil />}
                            tooltip="Edit"
                            onClick={() => openEditModal(definition)}
                            disabledReason={restrictionReason}
                        />
                        <LemonButton
                            size="small"
                            status="danger"
                            icon={<IconTrash />}
                            tooltip="Delete"
                            onClick={() => confirmDelete(definition)}
                            disabledReason={restrictionReason}
                        />
                    </div>
                )
            },
        },
    ]

    return (
        <div className="flex flex-col gap-2">
            <div className="flex justify-end">
                <LemonButton
                    type="primary"
                    icon={<IconPlus />}
                    // Lock the target: this page only manages one target, so the modal shouldn't offer
                    // the "Attach to" switch.
                    onClick={() => openCreateModal(targetType as CustomPropertyTargetType, true)}
                    disabledReason={restrictionReason}
                >
                    Add {labels.entity} property
                </LemonButton>
            </div>
            <LemonTable
                columns={columns}
                dataSource={profileDefinitions}
                loading={definitionsLoading}
                rowKey="id"
                expandable={{
                    rowExpandable: (definition) => !!definition.source,
                    onRowExpand: (definition) => definition.source && loadRuns({ sourceId: definition.source.id }),
                    expandedRowRender: (definition) =>
                        definition.source ? (
                            <ProfilePropertyRuns sourceId={definition.source.id} labels={labels} />
                        ) : null,
                }}
                emptyState={`No warehouse-backed ${labels.entity} properties yet. Add one to sync warehouse columns onto ${labels.entityPlural}.`}
            />
            <CustomPropertyModal />
        </div>
    )
}

export function WarehousePersonPropertiesSetting(): JSX.Element {
    return <WarehouseProfilePropertiesSetting targetType="person" />
}

export function WarehouseGroupPropertiesSetting(): JSX.Element {
    return <WarehouseProfilePropertiesSetting targetType="group" />
}
