import { useActions, useValues } from 'kea'

import { IconExternal, IconPencil, IconPlus, IconRefresh, IconTrash } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TZLabel } from 'lib/components/TZLabel'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import type {
    CustomPropertyDefinitionApi,
    CustomPropertySourceApi,
    CustomPropertySyncRunApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { CustomPropertyTargetType, customPropertyDefinitionsLogic } from './customPropertyDefinitionsLogic'
import { CustomPropertyModal } from './CustomPropertyModal'
import { type SourceSyncStatusLevel, runOutcomeNote, sourceSyncStatus } from './customPropertyTypes'

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

// The stored trigger values, as something a person reading their run history can act on. 'manual' is
// the Backfill button; 'backfill' is the one the system runs itself when a mapping is set up.
const RUN_TRIGGERS: Record<string, { label: string; type: LemonTagType }> = {
    scheduled: { label: 'Scheduled', type: 'default' },
    sync: { label: 'Sync now', type: 'option' },
    manual: { label: 'Backfill', type: 'option' },
    backfill: { label: 'Auto backfill', type: 'default' },
}

// Labels that differ between the person- and group-target views of the same warehouse-sync machinery.
type ProfileLabels = { entity: string; entityPlural: string; keyColumn: string }
const LABELS_BY_TARGET: Record<'person' | 'group', ProfileLabels> = {
    person: { entity: 'person', entityPlural: 'people', keyColumn: 'Distinct ID column' },
    group: { entity: 'group', entityPlural: 'groups', keyColumn: 'Group key column' },
}

function RunCount({ value }: { value: number }): JSX.Element {
    return <span className={value ? 'font-medium' : 'text-secondary'}>{humanFriendlyNumber(value)}</span>
}

// The updated share, as a whole percent. 100% has to mean every changed row landed, so a near-miss
// stays at 99% instead of rounding up, and a tiny share reads as <1% instead of collapsing to 0%.
function updatedShare(existing: number, changed: number): string | null {
    if (changed <= 0) {
        return null
    }
    if (existing >= changed) {
        return '100%'
    }
    const share = existing / changed
    if (share < 0.01) {
        return '<1%'
    }
    return percentage(Math.min(share, 0.99), 0)
}

// Whether the source reads a materialized view rather than a synced table.
function bindsAView(source: CustomPropertySourceApi): boolean {
    return !!source.saved_query && !source.external_data_schema
}

// Where the bound table or view's own run history lives. Null when the source has no warehouse
// binding, or when the caller can't view what it reads.
function sourceRunsUrl(source: CustomPropertySourceApi): string | null {
    if (bindsAView(source)) {
        return source.saved_query ? urls.sqlEditor({ view_id: source.saved_query }) : null
    }
    if (!source.external_data_source || !source.external_data_schema) {
        return null
    }
    return urls.dataWarehouseSourceSchema(source.external_data_source, source.external_data_schema, 'syncs')
}

// Run history for one source, loaded lazily when its row is expanded. `syncsUrl` points at the
// warehouse table's own sync history, where a run that rode a failing import shows the real error.
function ProfilePropertyRuns({
    sourceId,
    labels,
    syncsUrl,
}: {
    sourceId: string
    labels: ProfileLabels
    syncsUrl: string | null
}): JSX.Element {
    const { runsBySourceId, runsLoadingBySourceId } = useValues(customPropertyDefinitionsLogic)
    const runs = runsBySourceId[sourceId] ?? []

    const columns: LemonTableColumns<CustomPropertySyncRunApi> = [
        {
            title: 'Status',
            tooltip:
                'Whether the run finished. A completed run that updated nobody is normal: a sync only looks at rows the warehouse import itself changed.',
            render: (_, run) => {
                const note = runOutcomeNote(run, labels.entityPlural)
                return (
                    <div className="flex items-center gap-2">
                        <Tooltip title={run.error ?? undefined}>
                            <LemonTag
                                type={TAG_TYPE_BY_RUN_STATUS[run.status] ?? 'default'}
                                icon={run.status === 'running' ? <Spinner /> : undefined}
                            >
                                {run.status}
                            </LemonTag>
                        </Tooltip>
                        {note && (
                            <Tooltip title={note.tooltip}>
                                <span className="text-secondary text-xs whitespace-nowrap">{note.label}</span>
                            </Tooltip>
                        )}
                    </div>
                )
            },
        },
        {
            title: 'Trigger',
            tooltip: 'What started the run: the table\'s sync schedule, or a "Sync now" or "Backfill" you asked for.',
            render: (_, run) => {
                const trigger = RUN_TRIGGERS[run.trigger]
                return <LemonTag type={trigger?.type ?? 'default'}>{trigger?.label ?? run.trigger}</LemonTag>
            },
        },
        {
            title: 'Rows read',
            tooltip:
                'Warehouse rows this sync staged. A sync only stages rows the import itself added or changed, so a quiet table reads zero.',
            align: 'right',
            render: (_, run) => <RunCount value={run.rows_read} />,
        },
        {
            title: 'Updated',
            tooltip: `How many ${labels.entityPlural} this run updated, out of the rows whose mapped values changed. Rows that already hold the values last sent are skipped, even on a full refresh.`,
            align: 'right',
            render: (_, run) => {
                const share = updatedShare(run.existing, run.changed)
                return (
                    <span className="whitespace-nowrap">
                        <RunCount value={run.existing} />
                        <span className="text-secondary">
                            {' '}
                            of {humanFriendlyNumber(run.changed)} changed{share ? ` (${share})` : ''}
                        </span>
                    </span>
                )
            },
        },
        {
            title: `Skipped (no ${labels.entity})`,
            tooltip: `Changed rows dropped because their key column value matched no existing ${labels.entity}. The most common reason a property never shows up.`,
            align: 'right',
            render: (_, run) => (
                <span className="text-secondary">{humanFriendlyNumber(run.skipped_missing_person)}</span>
            ),
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

    if (syncsUrl) {
        columns.push({
            title: '',
            width: 0,
            render: () => (
                <LemonButton
                    size="small"
                    icon={<IconExternal />}
                    to={syncsUrl}
                    targetBlank
                    tooltip="Open this table's sync history in the data warehouse to see import errors"
                />
            ),
        })
    }

    return (
        <LemonTable
            columns={columns}
            dataSource={runs}
            loading={runsLoadingBySourceId[sourceId] ?? false}
            rowKey="id"
            size="small"
            nouns={['run', 'runs']}
            emptyState="No runs yet."
        />
    )
}

// First-class Customer analytics view of the warehouse → person/group property sources: manages the
// column mappings, shows the next scheduled sync, lets you trigger a sync or backfill, and expands to
// run history. Parametrized by target so the person and group settings entries share one implementation.
function WarehouseProfilePropertiesSetting({ targetType }: { targetType: 'person' | 'group' }): JSX.Element {
    const { definitions, definitionsInitialLoading, triggeringSourceIds } = useValues(customPropertyDefinitionsLogic)
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
            title: 'Reads',
            tooltip: 'The warehouse table or materialized view this property reads its values from.',
            render: (_, definition) => {
                const source = definition.source
                const name = source?.saved_query_name ?? source?.table_name
                if (!source || !name) {
                    return <span className="text-secondary">—</span>
                }
                const url = sourceRunsUrl(source)
                return (
                    <span className="flex items-center gap-2">
                        {url ? <Link to={url}>{name}</Link> : <span>{name}</span>}
                        <LemonTag type="muted">{bindsAView(source) ? 'View' : 'Table'}</LemonTag>
                    </span>
                )
            },
        },
        {
            title: labels.keyColumn,
            tooltip: `The warehouse column holding each row's ${targetType === 'person' ? 'distinct ID' : 'group key'}. It's how a row is matched to ${labels.entityPlural} — rows with no match are skipped.`,
            render: (_, definition) =>
                definition.source?.key_column ? (
                    <code>{definition.source.key_column}</code>
                ) : (
                    <span className="text-secondary">—</span>
                ),
        },
        {
            title: 'Mapped properties',
            tooltip: `Which warehouse column is written to which ${labels.entity} property.`,
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
            tooltip: 'State of the most recent run. Expand the row to see the full history.',
            render: (_, definition) => {
                if (!definition.source) {
                    return <span className="text-secondary">—</span>
                }
                const latestRun = definition.source.latest_run
                if (latestRun?.status === 'running') {
                    return (
                        <Tooltip title="A sync or backfill is running for this table right now.">
                            <LemonTag type="primary" icon={<Spinner />}>
                                Syncing
                            </LemonTag>
                        </Tooltip>
                    )
                }
                const status = sourceSyncStatus(definition.source)
                // Only report an affected count for a finished run — an in-progress/failed run's count
                // isn't "the last run". status.tooltip is undefined for the synced/pending states, so
                // build the title from the present parts rather than interpolating undefined into it.
                const affected = latestRun?.status === 'completed' ? latestRun.existing : undefined
                const tooltipTitle =
                    [
                        status.tooltip,
                        affected != null
                            ? `${humanFriendlyNumber(affected)} ${labels.entityPlural} affected on the last run`
                            : null,
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
                        </span>
                    </Tooltip>
                )
            },
        },
        {
            title: 'Next sync',
            tooltip: "When the table's warehouse sync is next due. Approximate — it drifts if the schedule was paused.",
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
                            loading={triggering || running}
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
                // Only the first load blanks the table. Polling for a running sync refreshes the same
                // list every few seconds, and a skeleton on every poll would make the page unusable.
                loading={definitionsInitialLoading}
                rowKey="id"
                expandable={{
                    rowExpandable: (definition) => !!definition.source,
                    onRowExpand: (definition) => definition.source && loadRuns({ sourceId: definition.source.id }),
                    expandedRowRender: (definition) =>
                        definition.source ? (
                            <ProfilePropertyRuns
                                sourceId={definition.source.id}
                                labels={labels}
                                syncsUrl={sourceRunsUrl(definition.source)}
                            />
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
