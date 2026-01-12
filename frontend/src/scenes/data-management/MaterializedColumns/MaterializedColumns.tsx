import { useActions, useValues } from 'kea'

import { IconDatabase, IconPlus, IconRefresh } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTable, LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
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
    MaterializationType,
    MaterializedColumnSlot,
    MaterializedColumnSlotState,
    materializedColumnsLogic,
} from './materializedColumnsLogic'

export const scene: SceneExport = {
    component: MaterializedColumns,
    logic: materializedColumnsLogic,
}

type SlotColumn = LemonTableColumn<MaterializedColumnSlot, keyof MaterializedColumnSlot | undefined>

export function MaterializedColumns(): JSX.Element {
    const { user } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { slots, slotsLoading, slotUsage, showCreateModal, autoMaterializedColumns, autoMaterializedColumnsLoading } =
        useValues(materializedColumnsLogic)
    const { loadSlots, setShowCreateModal, deleteSlot } = useActions(materializedColumnsLogic)

    const propertyColumn: SlotColumn = {
        title: 'Property',
        render: function Render(_, slot: MaterializedColumnSlot): JSX.Element {
            return <div className="font-semibold">{slot.property_name}</div>
        },
    }

    const typeColumn: SlotColumn = {
        title: 'Type',
        render: function Render(_, slot: MaterializedColumnSlot): JSX.Element {
            return <LemonTag>{slot.property_type}</LemonTag>
        },
    }

    const materializationTypeColumn: SlotColumn = {
        title: 'Storage',
        render: function Render(_, slot: MaterializedColumnSlot): JSX.Element {
            const isEav = slot.materialization_type === MaterializationType.EAV
            return <LemonTag type={isEav ? 'highlight' : 'default'}>{isEav ? 'EAV Table' : 'DMAT Column'}</LemonTag>
        },
    }

    const slotIndexColumn: SlotColumn = {
        title: 'Column',
        render: function Render(_, slot: MaterializedColumnSlot): JSX.Element {
            // EAV doesn't use a specific column - data is accessed via JOIN
            if (slot.materialization_type === MaterializationType.EAV) {
                return <span className="text-muted">—</span>
            }

            // For DMAT, show the column name
            const typeToColumnName: Record<string, string> = {
                String: 'string',
                Numeric: 'numeric',
                Boolean: 'bool',
                DateTime: 'datetime',
            }
            const columnType = typeToColumnName[slot.property_type]
            if (!columnType) {
                throw new Error(
                    `Unsupported property type '${slot.property_type}' for materialized column. ` +
                        `Supported types: ${Object.keys(typeToColumnName).join(', ')}`
                )
            }
            return (
                <div className="font-mono text-xs">
                    dmat_{columnType}_{slot.slot_index}
                </div>
            )
        },
    }

    const stateColumn: SlotColumn = {
        title: 'State',
        render: function Render(_, slot: MaterializedColumnSlot): JSX.Element {
            const type: LemonTagType =
                slot.state === MaterializedColumnSlotState.READY
                    ? 'success'
                    : slot.state === MaterializedColumnSlotState.ERROR
                      ? 'danger'
                      : 'warning'
            return (
                <LemonTag type={type} className="uppercase">
                    {slot.state}
                </LemonTag>
            )
        },
    }

    const backfillColumn: SlotColumn = {
        title: 'Backfill UUID',
        render: function Render(_, slot: MaterializedColumnSlot): JSX.Element {
            return (
                <div className="text-xs text-muted">
                    {slot.backfill_temporal_workflow_id ? (
                        <span className="font-mono">{slot.backfill_temporal_workflow_id}</span>
                    ) : (
                        <span>—</span>
                    )}
                </div>
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
                <LemonButton
                    type="secondary"
                    size="small"
                    status="danger"
                    onClick={() => deleteSlot(slot.id)}
                    disabledReason={
                        slot.state === MaterializedColumnSlotState.BACKFILL
                            ? 'Cannot delete slot while backfill is in progress'
                            : undefined
                    }
                >
                    Delete
                </LemonButton>
            )
        },
    }

    const columns: SlotColumn[] = [
        propertyColumn,
        typeColumn,
        materializationTypeColumn,
        slotIndexColumn,
        stateColumn,
        backfillColumn,
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
                            <h3 className="text-lg font-semibold mb-2">Slot Usage Summary</h3>
                            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                                {Object.entries(slotUsage.usage).map(([type, usage]) => {
                                    const typedUsage = usage as { used: number; total: number; available: number }
                                    return (
                                        <div key={type} className="space-y-1">
                                            <div className="font-semibold">{type}</div>
                                            <div className="text-2xl">
                                                {typedUsage.used} / {typedUsage.total}
                                            </div>
                                            <div className="text-xs text-muted">
                                                {typedUsage.available} slot{typedUsage.available !== 1 ? 's' : ''}{' '}
                                                available
                                            </div>
                                        </div>
                                    )
                                })}
                            </div>
                        </div>

                        <LemonDivider />

                        <div className="flex justify-between items-center">
                            <h3 className="text-lg font-semibold">Materialized Slots</h3>
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
                                >
                                    Assign Slot
                                </LemonButton>
                            </div>
                        </div>

                        <LemonTable
                            loading={slotsLoading}
                            columns={columns}
                            dataSource={slots}
                            pagination={{ pageSize: 20 }}
                            emptyState="No materialized slots assigned yet. Click 'Assign Slot' to get started."
                        />

                        <LemonDivider />

                        <div>
                            <h3 className="text-lg font-semibold mb-2">Auto-Materialized Properties</h3>
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
