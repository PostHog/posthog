import { LemonButton, LemonCheckbox, LemonInput, LemonModal, LemonSwitch, LemonTable } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import { sourceWizardLogic } from '../../new/sourceWizardLogic'
import { SyncMethodForm } from './SyncMethodForm'

export default function SchemaForm(): JSX.Element {
    const { toggleSchemaShouldSync, openSyncMethodModal, updateSyncTimeOfDay, setIsProjectTime } =
        useActions(sourceWizardLogic)
    const { databaseSchema, isProjectTime } = useValues(sourceWizardLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            <div className="flex flex-col gap-2">
                <div>
                    <LemonTable
                        emptyState="No schemas found"
                        dataSource={databaseSchema}
                        columns={[
                            {
                                width: 0,
                                key: 'enabled',
                                render: (_, schema) => {
                                    return (
                                        <LemonCheckbox
                                            checked={schema.should_sync}
                                            onChange={(checked) => {
                                                toggleSchemaShouldSync(schema, checked)
                                            }}
                                            disabledReason={
                                                schema.sync_type === null
                                                    ? 'Please set up a sync method first'
                                                    : undefined
                                            }
                                        />
                                    )
                                },
                            },
                            {
                                title: 'Table',
                                key: 'table',
                                render: function RenderTable(_, schema) {
                                    return schema.table
                                },
                            },
                            {
                                title: 'Rows',
                                key: 'rows',
                                isHidden: !databaseSchema.some((schema) => schema.rows),
                                render: (_, schema) => {
                                    return schema.rows != null ? schema.rows : 'Unknown'
                                },
                            },
                            {
                                title: (
                                    <div className="flex items-center gap-2">
                                        <span>First Sync Time</span>
                                        <div className="flex items-center gap-1">
                                            <span>UTC</span>
                                            <LemonSwitch checked={isProjectTime} onChange={setIsProjectTime} />
                                            <span>{dayjs().format('z')}</span>
                                        </div>
                                    </div>
                                ),
                                key: 'sync_time_of_day_local',
                                render: function RenderSyncTimeOfDayLocal(_, schema) {
                                    const utcTime = schema.sync_time_of_day || '00:00:00'
                                    const localTime = isProjectTime
                                        ? dayjs
                                              .utc(`${dayjs().format('YYYY-MM-DD')}T${utcTime}`)
                                              .local()
                                              .tz(currentTeam?.timezone || 'UTC')
                                              .format('HH:mm:00')
                                        : utcTime

                                    return (
                                        <LemonInput
                                            type="time"
                                            disabled={!schema.should_sync}
                                            value={localTime.substring(0, 5)}
                                            onChange={(value) => {
                                                const newValue = `${value}:00`
                                                const utcValue = isProjectTime
                                                    ? dayjs(`${dayjs().format('YYYY-MM-DD')}T${newValue}`)
                                                          .utc()
                                                          .tz(currentTeam?.timezone || 'UTC')
                                                          .format('HH:mm:00')
                                                    : newValue
                                                updateSyncTimeOfDay(schema, utcValue)
                                            }}
                                        />
                                    )
                                },
                            },
                            {
                                key: 'sync_type',
                                title: 'Sync method',
                                align: 'right',
                                tooltip:
                                    'Full refresh will refresh the full table on every sync, whereas incremental will only sync new and updated rows since the last sync',
                                render: (_, schema) => {
                                    if (!schema.sync_type) {
                                        return (
                                            <div className="justify-end flex">
                                                <LemonButton
                                                    className="my-1"
                                                    type="primary"
                                                    onClick={() => openSyncMethodModal(schema)}
                                                >
                                                    Set up
                                                </LemonButton>
                                            </div>
                                        )
                                    }

                                    return (
                                        <div className="justify-end flex">
                                            <LemonButton
                                                className="my-1"
                                                size="small"
                                                type="secondary"
                                                onClick={() => openSyncMethodModal(schema)}
                                            >
                                                {schema.sync_type === 'full_refresh' ? 'Full refresh' : 'Incremental'}
                                            </LemonButton>
                                        </div>
                                    )
                                },
                            },
                        ]}
                    />
                </div>
            </div>
            <SyncMethodModal />
        </>
    )
}

const SyncMethodModal = (): JSX.Element => {
    const { cancelSyncMethodModal, updateSchemaSyncType, toggleSchemaShouldSync } = useActions(sourceWizardLogic)
    const { syncMethodModalOpen, currentSyncMethodModalSchema } = useValues(sourceWizardLogic)

    if (!currentSyncMethodModalSchema) {
        return <></>
    }

    return (
        <LemonModal
            title={`Sync method for ${currentSyncMethodModalSchema.table}`}
            isOpen={syncMethodModalOpen}
            onClose={cancelSyncMethodModal}
        >
            <SyncMethodForm
                schema={currentSyncMethodModalSchema}
                onClose={cancelSyncMethodModal}
                onSave={(syncType, incrementalField, incrementalFieldType) => {
                    if (syncType === 'incremental') {
                        updateSchemaSyncType(
                            currentSyncMethodModalSchema,
                            syncType,
                            incrementalField,
                            incrementalFieldType
                        )
                    } else {
                        updateSchemaSyncType(currentSyncMethodModalSchema, syncType ?? null, null, null)
                    }

                    toggleSchemaShouldSync(currentSyncMethodModalSchema, true)
                    cancelSyncMethodModal()
                }}
            />
        </LemonModal>
    )
}
