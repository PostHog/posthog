import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonModal, LemonSwitch, LemonTable, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { syncAnchorIntervalToHumanReadable, SyncTypeLabelMap } from 'scenes/data-warehouse/utils'
import { teamLogic } from 'scenes/teamLogic'

import { ExternalDataSourceSyncSchema } from '~/types'

import { sourceWizardLogic } from '../../new/sourceWizardLogic'
import { SyncMethodForm } from './SyncMethodForm'

export default function SchemaForm(): JSX.Element {
    const { toggleSchemaShouldSync, openSyncMethodModal, updateSyncTimeOfDay, setIsProjectTime } =
        useActions(sourceWizardLogic)
    const { databaseSchema, isProjectTime } = useValues(sourceWizardLogic)
    const { currentTeam } = useValues(teamLogic)

    const onClickCheckbox = (schema: ExternalDataSourceSyncSchema, checked: boolean): void => {
        if (schema.sync_type === null) {
            openSyncMethodModal(schema)
            return
        }
        toggleSchemaShouldSync(schema, checked)
    }

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
                                render: function RenderEnabled(_, schema) {
                                    return (
                                        <LemonCheckbox
                                            checked={schema.should_sync}
                                            onChange={(checked) => onClickCheckbox(schema, checked)}
                                        />
                                    )
                                },
                            },
                            {
                                title: 'Table',
                                key: 'table',
                                render: function RenderTable(_, schema) {
                                    return (
                                        <span
                                            className="font-mono cursor-pointer"
                                            onClick={() => onClickCheckbox(schema, !schema.should_sync)}
                                        >
                                            {schema.table}
                                        </span>
                                    )
                                },
                            },
                            {
                                title: 'Rows',
                                key: 'rows',
                                isHidden: !databaseSchema.some((schema) => schema.rows),
                                render: function RenderRows(_, schema) {
                                    return schema.rows != null ? schema.rows : 'Unknown'
                                },
                            },
                            {
                                title: (
                                    <div className="flex items-center gap-2">
                                        <span>Anchor Time</span>
                                        <div className="flex items-center gap-1">
                                            <span>UTC</span>
                                            {currentTeam?.timezone !== 'UTC' && currentTeam?.timezone !== 'GMT' && (
                                                <>
                                                    <LemonSwitch checked={isProjectTime} onChange={setIsProjectTime} />
                                                    <span>{currentTeam?.timezone || 'UTC'}</span>
                                                </>
                                            )}
                                        </div>
                                    </div>
                                ),
                                key: 'sync_time_of_day',
                                tooltip:
                                    'The sync interval will be offset from the anchor time. This will not apply to sync intervals one hour or less.',
                                render: function RenderSyncTimeOfDay(_, schema) {
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
                                                          .tz(currentTeam?.timezone || 'UTC')
                                                          .utc()
                                                          .format('HH:mm:00')
                                                    : newValue
                                                updateSyncTimeOfDay(schema, utcValue)
                                            }}
                                            suffix={
                                                <Tooltip
                                                    interactive={schema.should_sync}
                                                    title={syncAnchorIntervalToHumanReadable(utcTime, '6hour')}
                                                >
                                                    <IconInfo className="text-muted-alt" />
                                                </Tooltip>
                                            }
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
                                render: function RenderSyncType(_, schema) {
                                    if (!schema.sync_type) {
                                        return (
                                            <div className="justify-end flex">
                                                <LemonButton
                                                    className="my-1"
                                                    type="primary"
                                                    onClick={() => openSyncMethodModal(schema)}
                                                    size="small"
                                                >
                                                    Configure
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
                                                {SyncTypeLabelMap[schema.sync_type]}
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
            title={
                <>
                    Sync method for <span className="font-mono">{currentSyncMethodModalSchema.table}</span>
                </>
            }
            isOpen={syncMethodModalOpen}
            onClose={cancelSyncMethodModal}
        >
            <SyncMethodForm
                schema={currentSyncMethodModalSchema}
                onClose={cancelSyncMethodModal}
                onSave={(syncType, incrementalField, incrementalFieldType) => {
                    if (syncType === 'incremental' || syncType === 'append') {
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
