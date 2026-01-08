import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconPencil, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { CoreEvent, NodeKind, SchemaMap } from '~/queries/schema/schema-general'

import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import { getGoalFilterSummary, getGoalTypeLabel, getTableColumns } from '../../utils/coreEventUtils'
import { SchemaMapModal } from '../SchemaMapModal'
import { conversionGoalDescription, getConfiguredConversionGoalsLabel } from './constants'

const DEFAULT_SCHEMA_MAP: SchemaMap = {
    utm_campaign_name: 'utm_campaign',
    utm_source_name: 'utm_source',
}

interface SchemaMapFormState {
    event: CoreEvent | null
    schemaMap: SchemaMap
    isEditing: boolean // true if editing existing mapping, false if adding new
    existingMappingId?: string
}

export function ConversionGoalsConfiguration({
    hideTitle = false,
    hideDescription = false,
}: {
    hideTitle?: boolean
    hideDescription?: boolean
}): JSX.Element {
    const {
        enabledCoreEvents,
        availableCoreEvents,
        teamCoreEvents,
        goalMappings,
        dataWarehouseTables,
        conversion_goals: legacyConversionGoals,
    } = useValues(marketingAnalyticsSettingsLogic)
    const { addGoalMapping, updateGoalMapping, removeGoalMapping, removeConversionGoal } = useActions(
        marketingAnalyticsSettingsLogic
    )

    const [schemaMapForm, setSchemaMapForm] = useState<SchemaMapFormState | null>(null)

    // Get available columns for the current event's table
    const availableColumns = useMemo(() => {
        if (!schemaMapForm?.event) {
            return []
        }
        return getTableColumns(schemaMapForm.event, dataWarehouseTables || [])
    }, [schemaMapForm?.event, dataWarehouseTables])

    const handleSelectGoal = (eventId: string): void => {
        const event = availableCoreEvents.find((e) => e.id === eventId)
        if (!event) {
            return
        }

        // For DW events, show schema_map configuration modal
        if (event.filter.kind === NodeKind.DataWarehouseNode) {
            setSchemaMapForm({
                event,
                schemaMap: { ...DEFAULT_SCHEMA_MAP },
                isEditing: false,
            })
        } else {
            // For events/actions, add directly without schema_map
            addGoalMapping(event.id)
        }
    }

    const handleEditSchemaMap = (event: CoreEvent): void => {
        const existingMapping = goalMappings.find((m) => m.core_event.id === event.id)
        setSchemaMapForm({
            event,
            schemaMap: existingMapping?.schema_map || { ...DEFAULT_SCHEMA_MAP },
            isEditing: true,
            existingMappingId: existingMapping?.id,
        })
    }

    const handleSaveSchemaMap = (): void => {
        if (!schemaMapForm?.event) {
            return
        }

        if (schemaMapForm.isEditing && schemaMapForm.existingMappingId) {
            updateGoalMapping(schemaMapForm.existingMappingId, schemaMapForm.schemaMap)
        } else {
            addGoalMapping(schemaMapForm.event.id, schemaMapForm.schemaMap)
        }
        setSchemaMapForm(null)
    }

    const handleRemoveGoal = (coreEventId: string): void => {
        const mapping = goalMappings.find((m) => m.core_event.id === coreEventId)
        if (mapping) {
            removeGoalMapping(mapping.id)
        }
    }

    const hasTeamGoals = teamCoreEvents.length > 0
    const hasAvailableGoals = availableCoreEvents.length > 0
    const hasLegacyGoals = legacyConversionGoals.length > 0

    return (
        <SceneSection
            title={!hideTitle ? 'Conversion goals' : undefined}
            description={!hideDescription ? conversionGoalDescription : undefined}
        >
            {/* Deprecation banner for legacy conversion goals */}
            {hasLegacyGoals && (
                <LemonBanner type="warning" className="mb-4">
                    Legacy conversion goals are being replaced by Core Events. Migrate to manage your goals centrally.
                </LemonBanner>
            )}

            <div className="space-y-4">
                {/* Legacy Conversion Goals - shown first when present */}
                {hasLegacyGoals && (
                    <div className="border border-warning rounded p-4 space-y-3 bg-warning-highlight">
                        <div className="flex justify-between items-center">
                            <h4 className="font-medium text-warning-dark">Legacy conversion goals (deprecated)</h4>
                            <LemonButton type="secondary" size="small" to={urls.coreEvents()}>
                                Migrate to Core Events
                            </LemonButton>
                        </div>
                        <p className="text-sm text-muted">
                            These goals use the old format and should be migrated to Core Events. They will continue to
                            work but are no longer recommended.
                        </p>
                        <LemonTable
                            rowKey={(item) => item.conversion_goal_id}
                            dataSource={legacyConversionGoals}
                            size="small"
                            columns={[
                                {
                                    key: 'name',
                                    title: 'Goal name',
                                    render: (_, goal) => (
                                        <span className="font-medium">{goal.conversion_goal_name}</span>
                                    ),
                                },
                                {
                                    key: 'type',
                                    title: 'Type',
                                    render: (_, goal) => {
                                        if (goal.kind === NodeKind.EventsNode) {
                                            return 'Event'
                                        }
                                        if (goal.kind === NodeKind.ActionsNode) {
                                            return 'Action'
                                        }
                                        if (goal.kind === NodeKind.DataWarehouseNode) {
                                            return 'Data warehouse'
                                        }
                                        return 'Unknown'
                                    },
                                },
                                {
                                    key: 'actions',
                                    title: 'Actions',
                                    width: 100,
                                    render: (_, goal) => (
                                        <LemonButton
                                            icon={<IconTrash />}
                                            size="small"
                                            status="danger"
                                            onClick={() => removeConversionGoal(goal.conversion_goal_id)}
                                            tooltip="Remove legacy goal"
                                        />
                                    ),
                                },
                            ]}
                        />
                    </div>
                )}

                {/* Enabled Core Events */}
                <div>
                    <div className="flex justify-between items-center gap-4">
                        <h4 className="font-medium">{getConfiguredConversionGoalsLabel(enabledCoreEvents.length)}</h4>
                        <div className="flex gap-2 items-center">
                            {hasTeamGoals && hasAvailableGoals && (
                                <LemonSelect
                                    placeholder="Add core event..."
                                    options={availableCoreEvents.map((event) => ({
                                        value: event.id,
                                        label: event.name,
                                        labelInMenu: (
                                            <div className="flex flex-col">
                                                <span className="font-medium">{event.name}</span>
                                                <span className="text-xs text-muted">
                                                    {getGoalTypeLabel(event)}: {getGoalFilterSummary(event)}
                                                </span>
                                            </div>
                                        ),
                                    }))}
                                    onChange={(value) => value && handleSelectGoal(value)}
                                    value={null}
                                    size="small"
                                />
                            )}
                            <LemonButton type="secondary" size="small" to={urls.coreEvents()}>
                                Manage Core Events
                            </LemonButton>
                        </div>
                    </div>
                    <p className="text-sm text-muted mt-1">
                        Core events enabled for marketing analytics. Manage your core events in the Core Events page.
                    </p>
                </div>

                <LemonTable
                    rowKey={(item) => item.id}
                    dataSource={enabledCoreEvents}
                    columns={[
                        {
                            key: 'name',
                            title: 'Goal name',
                            render: (_, event: CoreEvent) => <span className="font-medium">{event.name}</span>,
                        },
                        {
                            key: 'type',
                            title: 'Type',
                            render: (_, event: CoreEvent) => getGoalTypeLabel(event),
                        },
                        {
                            key: 'filter',
                            title: 'Event/Action/Table',
                            render: (_, event: CoreEvent) => (
                                <span className="text-muted">{getGoalFilterSummary(event)}</span>
                            ),
                        },
                        {
                            key: 'schema',
                            title: 'Attribution mapping',
                            render: (_, event: CoreEvent) => {
                                if (event.filter.kind !== NodeKind.DataWarehouseNode) {
                                    return <span className="text-muted">Pageview-based</span>
                                }
                                const mapping = goalMappings.find((m) => m.core_event.id === event.id)
                                if (!mapping?.schema_map) {
                                    return <span className="text-muted">Not configured</span>
                                }
                                return (
                                    <div className="text-xs text-muted">
                                        <div>Campaign: {mapping.schema_map.utm_campaign_name}</div>
                                        <div>Source: {mapping.schema_map.utm_source_name}</div>
                                    </div>
                                )
                            },
                        },
                        {
                            key: 'actions',
                            title: 'Actions',
                            width: 100,
                            render: (_, event: CoreEvent) => (
                                <div className="flex gap-1">
                                    {event.filter.kind === NodeKind.DataWarehouseNode && (
                                        <LemonButton
                                            icon={<IconPencil />}
                                            size="small"
                                            onClick={() => handleEditSchemaMap(event)}
                                            tooltip="Edit attribution mapping"
                                        />
                                    )}
                                    <LemonButton
                                        icon={<IconTrash />}
                                        size="small"
                                        status="danger"
                                        onClick={() => handleRemoveGoal(event.id)}
                                        tooltip="Remove from marketing analytics"
                                    />
                                </div>
                            ),
                        },
                    ]}
                    emptyState={
                        hasTeamGoals
                            ? 'No core events enabled. Use the dropdown above to add one.'
                            : "No core events defined yet. Click 'Manage Core Events' to create your first one."
                    }
                />
            </div>

            <SchemaMapModal
                isOpen={!!schemaMapForm}
                onClose={() => setSchemaMapForm(null)}
                title={
                    schemaMapForm?.isEditing
                        ? `Edit attribution mapping for "${schemaMapForm.event?.name}"`
                        : `Configure attribution mapping for "${schemaMapForm?.event?.name}"`
                }
                goalName={schemaMapForm?.event?.name || ''}
                schemaMap={schemaMapForm?.schemaMap || { utm_campaign_name: '', utm_source_name: '' }}
                onSchemaMapChange={(newSchemaMap) =>
                    setSchemaMapForm((prev) => (prev ? { ...prev, schemaMap: newSchemaMap } : null))
                }
                onConfirm={handleSaveSchemaMap}
                confirmText={schemaMapForm?.isEditing ? 'Save' : 'Add goal'}
                availableColumns={availableColumns}
            />
        </SceneSection>
    )
}
