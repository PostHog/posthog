import { useActions, useValues } from 'kea'

import { IconDatabase, IconPlus, IconRefresh } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTable, LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip/Tooltip'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { CreateSlotModal } from './CreateSlotModal'
import {
    AutoMaterializedColumn,
    MaterializedColumnSlot,
    MaterializedColumnSlotState,
    materializedColumnsLogic,
} from './materializedColumnsLogic'

export const scene: SceneExport = {
    component: MaterializedColumns,
    logic: materializedColumnsLogic,
}

type SlotColumn = LemonTableColumn<MaterializedColumnSlot, keyof MaterializedColumnSlot | undefined>

function dmatColumnName(slotIndex: number): string {
    return `dmat_string_${slotIndex}`
}

const STATE_TAG_TYPE: Record<MaterializedColumnSlotState, LemonTagType> = {
    [MaterializedColumnSlotState.PENDING]: 'default',
    [MaterializedColumnSlotState.BACKFILL]: 'warning',
    [MaterializedColumnSlotState.READY]: 'success',
    [MaterializedColumnSlotState.ERROR]: 'danger',
}

const STATE_TOOLTIP: Record<MaterializedColumnSlotState, string> = {
    [MaterializedColumnSlotState.PENDING]:
        'Queued. The next weekly backfill cycle will assign a column and start the historical backfill.',
    [MaterializedColumnSlotState.BACKFILL]:
        'New events are populating the column; historical events are being backfilled. Queries still use JSON until READY.',
    [MaterializedColumnSlotState.READY]: 'Active — HogQL reads from the materialized column.',
    [MaterializedColumnSlotState.ERROR]:
        'Backfill failed. Click "Retry" to put it back in the queue for the next cycle.',
}

export function MaterializedColumns(): JSX.Element {
    const { user } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { slots, slotsLoading, slotUsage, showCreateModal, autoMaterializedColumns, autoMaterializedColumnsLoading } =
        useValues(materializedColumnsLogic)
    const { loadSlots, setShowCreateModal, deleteSlot, retrySlot } = useActions(materializedColumnsLogic)

    const propertyColumn: SlotColumn = {
        title: 'Property',
        render: function Render(_, slot: MaterializedColumnSlot): JSX.Element {
            return (
                <div>
                    <div className="font-semibold">{slot.property_definition_details?.name}</div>
                    <div className="text-xs text-muted">ID: {slot.property_definition}</div>
                </div>
            )
        },
    }

    const slotIndexColumn: SlotColumn = {
        title: 'Column',
        render: function Render(_, slot: MaterializedColumnSlot): JSX.Element {
            // PENDING slots have no column assigned yet — the weekly cron picks one.
            if (slot.slot_index === null || slot.slot_index === undefined) {
                return <span className="text-muted text-xs italic">awaiting next weekly cycle</span>
            }

            const current = <span className="font-mono">{dmatColumnName(slot.slot_index)}</span>

            // During compaction the slot is being repacked: ingestion writes to both columns,
            // HogQL still reads the old one until the workflow swaps them after the mutation.
            if (slot.compaction_target_slot_index !== null && slot.compaction_target_slot_index !== undefined) {
                return (
                    <Tooltip title="Compaction in flight: ingestion is dual-writing to both columns. HogQL keeps reading the old column until the workflow swaps them after the historical backfill mutation completes.">
                        <div className="font-mono text-xs">
                            {current}
                            <span className="mx-1 text-muted">→</span>
                            <span>{dmatColumnName(slot.compaction_target_slot_index)}</span>
                        </div>
                    </Tooltip>
                )
            }

            return current
        },
    }

    const stateColumn: SlotColumn = {
        title: 'State',
        render: function Render(_, slot: MaterializedColumnSlot): JSX.Element {
            const state = slot.state as MaterializedColumnSlotState
            return (
                <Tooltip title={STATE_TOOLTIP[state] ?? ''}>
                    <LemonTag type={STATE_TAG_TYPE[state] ?? 'default'} className="uppercase">
                        {slot.state}
                    </LemonTag>
                </Tooltip>
            )
        },
    }

    const errorColumn: SlotColumn = {
        title: 'Error',
        render: function Render(_, slot: MaterializedColumnSlot): JSX.Element {
            if (!slot.error_message) {
                return <span className="text-muted">—</span>
            }
            return (
                <Tooltip title={slot.error_message}>
                    <span className="text-xs text-danger truncate block max-w-xs">{slot.error_message}</span>
                </Tooltip>
            )
        },
    }

    const createdAtColumn: SlotColumn = {
        title: 'Created',
        render: function Render(_, slot: MaterializedColumnSlot): JSX.Element {
            return <div className="text-xs">{humanFriendlyDetailedTime(slot.created_at)}</div>
        },
    }

    const actionsColumn: SlotColumn = {
        title: '',
        render: function Render(_, slot: MaterializedColumnSlot): JSX.Element {
            return (
                <div className="flex gap-2">
                    {slot.state === MaterializedColumnSlotState.ERROR && (
                        <LemonButton type="secondary" size="small" onClick={() => retrySlot(slot.id)}>
                            Retry
                        </LemonButton>
                    )}
                    <LemonButton
                        type="secondary"
                        size="small"
                        status="danger"
                        onClick={() => deleteSlot(slot.id)}
                        disabledReason={
                            slot.state === MaterializedColumnSlotState.BACKFILL
                                ? 'Cannot delete while the backfill mutation is in flight — wait for it to complete or fail'
                                : undefined
                        }
                    >
                        Delete
                    </LemonButton>
                </div>
            )
        },
    }

    const columns: SlotColumn[] = [
        propertyColumn,
        slotIndexColumn,
        stateColumn,
        errorColumn,
        createdAtColumn,
        actionsColumn,
    ]

    if (!user?.is_staff) {
        return (
            <SceneContent>
                <SceneTitleSection
                    name="Materialized Columns"
                    description="Only users with staff access can manage materialized columns. Please contact your instance admin."
                    resourceType={{
                        type: 'materialized_columns',
                        forceIcon: <IconDatabase />,
                    }}
                />
                <p>Only users with staff access can manage materialized columns. Please contact your instance admin.</p>
                <p>
                    If you're an admin and don't have access, set <code>is_staff=true</code> for your user on the
                    PostgreSQL <code>posthog_user</code> table.
                </p>
                <SceneDivider />
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={`Materialized Columns - ${currentTeam?.name || 'Loading...'}`}
                description="Manage materialized column slot assignments for this team."
                markdown
                resourceType={{
                    type: 'materialized_columns',
                    forceIcon: <IconDatabase />,
                }}
            />

            <div className="space-y-4">
                {currentTeam && slotUsage && (
                    <>
                        <div className="bg-bg-light rounded p-4">
                            <h3 className="text-lg font-semibold mb-2">Slot usage</h3>
                            <div className="grid grid-cols-2 gap-4">
                                <div className="space-y-1">
                                    <div className="font-semibold">Used</div>
                                    <div className="text-2xl">
                                        {slotUsage.used_total} / {slotUsage.max_slots_per_team}
                                    </div>
                                </div>
                                <div className="space-y-1">
                                    <div className="font-semibold">Available</div>
                                    <div className="text-2xl">{slotUsage.available}</div>
                                </div>
                            </div>
                            <div className="text-xs text-muted mt-2">
                                Cap is team-wide. Newly assigned properties stay PENDING until the next weekly backfill
                                cycle.
                            </div>
                        </div>

                        <LemonDivider />

                        <div className="flex justify-between items-center">
                            <h3 className="text-lg font-semibold">Materialized slots</h3>
                            <div className="flex gap-2">
                                <LemonButton
                                    icon={slotsLoading ? <Spinner /> : <IconRefresh />}
                                    onClick={loadSlots}
                                    type="secondary"
                                    size="small"
                                >
                                    Refresh
                                </LemonButton>
                                <LemonButton
                                    icon={<IconPlus />}
                                    onClick={() => setShowCreateModal(true)}
                                    type="primary"
                                    size="small"
                                    disabledReason={
                                        slotUsage.available <= 0
                                            ? `Team is at the cap of ${slotUsage.max_slots_per_team} slots`
                                            : undefined
                                    }
                                >
                                    Assign slot
                                </LemonButton>
                            </div>
                        </div>

                        <LemonTable
                            loading={slotsLoading}
                            columns={columns}
                            dataSource={slots}
                            pagination={{ pageSize: 20 }}
                            emptyState="No materialized slots assigned yet. Click 'Assign slot' to get started."
                        />

                        <LemonDivider />

                        <div>
                            <h3 className="text-lg font-semibold mb-2">Auto-materialized properties</h3>
                            <p className="text-sm text-muted mb-4">
                                These properties are already automatically materialized by PostHog. You're already
                                getting all the performance gains we can provide!
                            </p>
                            {autoMaterializedColumnsLoading ? (
                                <div className="flex items-center justify-center py-8">
                                    <Spinner />
                                </div>
                            ) : autoMaterializedColumns.length === 0 ? (
                                <div className="text-muted text-sm">No auto-materialized properties found.</div>
                            ) : (
                                <div className="flex flex-wrap gap-2">
                                    {autoMaterializedColumns.map((column: AutoMaterializedColumn) => (
                                        <LemonTag key={column.column_name} type="default">
                                            {column.property_name}
                                        </LemonTag>
                                    ))}
                                </div>
                            )}
                        </div>

                        {showCreateModal && <CreateSlotModal />}
                    </>
                )}
            </div>
        </SceneContent>
    )
}
