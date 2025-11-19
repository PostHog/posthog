import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconDatabase, IconPlus, IconRefresh } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTable, LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { CreateSlotModal } from './CreateSlotModal'
import {
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
    const { slots, slotsLoading, selectedTeamId, slotUsage, teams, showCreateModal } =
        useValues(materializedColumnsLogic)
    const { loadSlots, setSelectedTeamId, setShowCreateModal, deleteSlot } = useActions(materializedColumnsLogic)

    useEffect(() => {
        if (selectedTeamId) {
            loadSlots()
        }
    }, [selectedTeamId, loadSlots])

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

    const typeColumn: SlotColumn = {
        title: 'Type',
        render: function Render(_, slot: MaterializedColumnSlot): JSX.Element {
            return <LemonTag>{slot.property_type}</LemonTag>
        },
    }

    const slotIndexColumn: SlotColumn = {
        title: 'Slot Index',
        render: function Render(_, slot: MaterializedColumnSlot): JSX.Element {
            return (
                <div className="font-mono">
                    mat_{slot.property_type?.toLowerCase()}_{slot.slot_index}
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
                    {slot.backfill_temporal_uuid ? (
                        <span className="font-mono">{slot.backfill_temporal_uuid}</span>
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
                name="Materialized Columns"
                description="Manage materialized column slot assignments for teams."
                markdown
                resourceType={{
                    type: 'materialized_columns',
                    forceIcon: <IconDatabase />,
                }}
            />

            <div className="space-y-4">
                <div className="flex items-end gap-2">
                    <div className="flex-1">
                        <LemonLabel>Select Team</LemonLabel>
                        <LemonSelect
                            placeholder="Select a team..."
                            options={teams.map((team) => ({
                                label: `${team.name} (ID: ${team.id})`,
                                value: team.id,
                            }))}
                            value={selectedTeamId}
                            onChange={setSelectedTeamId}
                        />
                    </div>
                </div>

                {selectedTeamId && slotUsage && (
                    <>
                        <div className="bg-bg-light rounded p-4">
                            <h3 className="text-lg font-semibold mb-2">Slot Usage Summary</h3>
                            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                                {Object.entries(slotUsage.usage).map(([type, usage]) => (
                                    <div key={type} className="space-y-1">
                                        <div className="font-semibold">{type}</div>
                                        <div className="text-2xl">
                                            {usage.used} / {usage.total}
                                        </div>
                                        <div className="text-xs text-muted">
                                            {usage.available} slot{usage.available !== 1 ? 's' : ''} available
                                        </div>
                                    </div>
                                ))}
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

                        {showCreateModal && <CreateSlotModal />}
                    </>
                )}
            </div>
        </SceneContent>
    )
}
