import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconInfo } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonInput,
    LemonModal,
    LemonSwitch,
    LemonTable,
    LemonTag,
    Link,
    Tooltip,
    lemonToast,
} from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { SyncTypeLabelMap, syncAnchorIntervalToHumanReadable } from 'scenes/data-warehouse/utils'
import { teamLogic } from 'scenes/teamLogic'

import { ExternalDataSourceSyncSchema, IncrementalField } from '~/types'

import { sourceWizardLogic } from '../../new/sourceWizardLogic'
import { SyncMethodForm } from './SyncMethodForm'

export default function SchemaForm(): JSX.Element {
    const { toggleSchemaShouldSync, openSyncMethodModal, updateSyncTimeOfDay, setIsProjectTime, updateSchemaSyncType } =
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

    const resolveIncrementalField = (fields: IncrementalField[]): IncrementalField | undefined => {
        const timestampType = 'timestamp'
        // check for timestamp field matching "updated_at" or "updatedAt" case insensitive
        const updatedAt = fields.find((field) => {
            const regex = /^updated/i
            return regex.test(field.field) && field.field_type === timestampType
        })
        if (updatedAt) {
            return updatedAt
        }
        // fallback to timestamp field matching "created_at" or "createdAt" case insensitive
        const createdAt = fields.find((field) => {
            const regex = /^created/i
            return regex.test(field.field) && field.field_type === timestampType
        })
        if (createdAt) {
            return createdAt
        }
        // fallback to any timestamp field
        const timestamp = fields.find((field) => {
            return field.field_type === timestampType
        })
        if (timestamp) {
            return timestamp
        }
        // fallback to fields matching "id" or "uuid" case insensitive
        const id = fields.find((field) => {
            const idRegex = /^id/i
            if (idRegex.test(field.field)) {
                return true
            }
            const uuidRegex = /^uuid/i
            return uuidRegex.test(field.field)
        })
        if (id) {
            return id
        }
        // leave unset and require user configuration
        return undefined
    }

    const smartConfigureTables = (databaseSchema: ExternalDataSourceSyncSchema[]): void => {
        databaseSchema.forEach((schema) => {
            if (schema.sync_type === null) {
                // Use incremental if available
                if (schema.incremental_available || schema.append_available) {
                    const method = schema.incremental_available ? 'incremental' : 'append'
                    const field = resolveIncrementalField(schema.incremental_fields)
                    if (field) {
                        updateSchemaSyncType(schema, method, field.field, field.field_type)
                        toggleSchemaShouldSync(schema, true)
                    }
                } else {
                    updateSchemaSyncType(schema, 'full_refresh', null, null)
                    toggleSchemaShouldSync(schema, true)
                }
            }
        })
        lemonToast.info(
            "We've setup some defaults for you! Please take a look to make sure you're happy with the results."
        )
    }

    useEffect(() => {
        window.scrollTo(0, 0)
    }, [])

    return (
        <>
            <div className="my-1">
                Configure sync methods for your tables below or{' '}
                <Link
                    tooltip="Incremental refresh is the default where supported. If incremental refresh is not available, we fallback to append-only refresh. Full refresh is only selected if no other option is available. We also attempt to identify appropriate columns to use as keys for incremental and append-only sync methods."
                    onClick={() => smartConfigureTables(databaseSchema)}
                >
                    let us choose reasonable defaults to start from.
                </Link>
            </div>
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
                                key: 'sync_field',
                                title: 'Sync field',
                                align: 'right',
                                tooltip:
                                    'Incremental and append-only refresh methods key on a unique field to determine the most up-to-date data.',
                                isHidden: !databaseSchema.some((schema) => schema.sync_type),
                                render: function RenderSyncType(_, schema) {
                                    if (schema.sync_type !== null && schema.incremental_field) {
                                        return (
                                            <>
                                                <span className="leading-5">{schema.incremental_field}</span>
                                                <LemonTag className="ml-2" type="success">
                                                    {schema.incremental_field_type}
                                                </LemonTag>
                                            </>
                                        )
                                    }
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
            <FullRefreshWarningModal />
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

const FullRefreshWarningModal = (): JSX.Element => {
    const { cancelFullRefreshWarningModal } = useActions(sourceWizardLogic)
    const { fullRefreshWarningModalOpen } = useValues(sourceWizardLogic)
    const { databaseSchema } = useValues(sourceWizardLogic)

    return (
        <LemonModal
            title={<>Heads up! Full refresh sync methods can rapidly increase your expense!</>}
            isOpen={fullRefreshWarningModalOpen}
            onClose={cancelFullRefreshWarningModal}
        >
            You currently have full refresh enabled as the sync method for the following tables:{' '}
            <ul>
                {databaseSchema.forEach((schema) => {
                    return <li className="font-mono">{schema.table} </li>
                })}
            </ul>
        </LemonModal>
    )
}
