import { LemonSelect, LemonSwitch, LemonTable, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { ExternalDataSourceSyncSchema } from '~/types'

import { sourceWizardLogic } from '../../new/sourceWizardLogic'

const getIncrementalSyncDisabledReason = (schema: ExternalDataSourceSyncSchema): string | undefined => {
    if (!schema.incremental_available) {
        return "Incremental replication isn't supported on this table"
    }

    if (schema.incremental_fields.length === 0) {
        return 'No incremental fields found on table'
    }
    return undefined
}

export default function SchemaForm(): JSX.Element {
    const { updateSchema } = useActions(sourceWizardLogic)
    const { databaseSchema } = useValues(sourceWizardLogic)

    return (
        <div className="flex flex-col gap-4">
            <LemonTable
                emptyState="No schemas found"
                dataSource={databaseSchema}
                columns={[
                    {
                        title: 'Table',
                        key: 'table',
                        render: function RenderTable(_, schema) {
                            return <span className="font-mono">{schema.table}</span>
                        },
                    },
                    {
                        title: 'Rows',
                        key: 'rows',
                        isHidden: !databaseSchema.some((s) => s.rows),
                        render: (_, schema) => (schema.rows != null ? schema.rows : 'Unknown'),
                    },
                    {
                        key: 'sync_type',
                        title: 'Sync method',
                        tooltip:
                            'Full refresh will refresh the full table on every sync, whereas incremental will only sync new/updated rows.',
                        render: (_, schema) => {
                            const incrementalSyncDisabledReason = getIncrementalSyncDisabledReason(schema)
                            const defaultIncrementalField = incrementalSyncDisabledReason
                                ? null
                                : schema.incremental_fields[0]?.field ?? null
                            const defaultIncrementalFieldType = incrementalSyncDisabledReason
                                ? null
                                : schema.incremental_fields[0]?.field_type ?? null

                            return (
                                <div className="py-2">
                                    <LemonSelect
                                        value={schema.sync_type ?? null}
                                        onChange={(val) =>
                                            updateSchema({
                                                ...schema,
                                                sync_type: val,
                                                incremental_field: defaultIncrementalField,
                                                incremental_field_type: defaultIncrementalFieldType,
                                            })
                                        }
                                        options={[
                                            { value: 'full_refresh', label: 'Full refresh' },
                                            {
                                                value: 'incremental',
                                                label: (
                                                    <>
                                                        Incremental
                                                        {!incrementalSyncDisabledReason && (
                                                            <LemonTag type="success" className="ml-2">
                                                                Recommended
                                                            </LemonTag>
                                                        )}
                                                    </>
                                                ),
                                                disabledReason: incrementalSyncDisabledReason,
                                            },
                                        ]}
                                        placeholder="Configure"
                                    />
                                </div>
                            )
                        },
                    },
                    {
                        key: 'incremental_field',
                        tooltip:
                            "When using incremental replication, we'll store the max value of the chosen field on each sync and only sync rows with a greater or equal value on the next run.\nYou should pick a field that increments or updates each time the row is updated, such as an updated_at timestamp.",
                        title: 'Incremental field',
                        render: (_, schema) => {
                            const incrementalSyncDisabledReason = getIncrementalSyncDisabledReason(schema)
                            const isIncremental = schema.sync_type === 'incremental'
                            return (
                                <div className="py-2">
                                    <LemonSelect
                                        value={schema.incremental_field ?? null}
                                        onChange={(val) =>
                                            updateSchema({
                                                ...schema,
                                                incremental_field: val,
                                                incremental_field_type:
                                                    schema.incremental_fields.find((f) => f.field === val)
                                                        ?.field_type ?? null,
                                            })
                                        }
                                        options={
                                            schema.incremental_fields?.map((f) => ({
                                                value: f.field,
                                                label: (
                                                    <>
                                                        {f.label}
                                                        <LemonTag type="success" className="ml-2">
                                                            {f.type}
                                                        </LemonTag>
                                                    </>
                                                ),
                                            })) ?? []
                                        }
                                        disabledReason={
                                            !isIncremental ? 'Select incremental first' : incrementalSyncDisabledReason
                                        }
                                        placeholder="None"
                                    />
                                </div>
                            )
                        },
                    },
                    {
                        width: 0,
                        key: 'enabled',
                        render: (_, schema) => {
                            const incrementalSyncDisabledReason = getIncrementalSyncDisabledReason(schema)
                            const defaultSyncType = incrementalSyncDisabledReason ? 'full_refresh' : 'incremental'
                            const defaultIncrementalField = incrementalSyncDisabledReason
                                ? null
                                : schema.incremental_fields[0]?.field ?? null
                            const defaultIncrementalFieldType = incrementalSyncDisabledReason
                                ? null
                                : schema.incremental_fields[0]?.field_type ?? null
                            return (
                                <LemonSwitch
                                    checked={schema.should_sync}
                                    onChange={(checked) =>
                                        updateSchema({
                                            ...schema,
                                            should_sync: checked,
                                            sync_type: schema.sync_type ?? defaultSyncType,
                                            incremental_field: schema.incremental_field ?? defaultIncrementalField,
                                            incremental_field_type:
                                                schema.incremental_field_type ?? defaultIncrementalFieldType,
                                        })
                                    }
                                />
                            )
                        },
                    },
                ]}
            />
        </div>
    )
}
