import { LemonSelect, LemonSelectOptionLeaf, LemonSwitch, LemonTable, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { ExternalDataSourceSyncSchema } from '~/types'

import { sourceWizardLogic } from '../../new/sourceWizardLogic'

const syncTypesToOptions = (
    schema: ExternalDataSourceSyncSchema
): LemonSelectOptionLeaf<ExternalDataSourceSyncSchema['sync_type']>[] => {
    const options: LemonSelectOptionLeaf<ExternalDataSourceSyncSchema['sync_type']>[] = []

    if (schema.sync_types.full_refresh) {
        options.push({ value: 'full_refresh', label: 'Full refresh' })
    }

    if (schema.sync_types.incremental) {
        options.push({ value: 'incremental', label: 'Incremental' })
    }

    return options
}

export default function PostgresSchemaForm(): JSX.Element {
    const { toggleSchemaShouldSync, updateSchemaSyncType } = useActions(sourceWizardLogic)
    const { databaseSchema } = useValues(sourceWizardLogic)
    const [toggleAllState, setToggleAllState] = useState(false)

    const toggleAllSwitches = (): void => {
        databaseSchema.forEach((schema) => {
            toggleSchemaShouldSync(schema, toggleAllState)
        })

        setToggleAllState(!toggleAllState)
    }

    return (
        <div className="flex flex-col gap-2">
            <div>
                <LemonTable
                    emptyState="No schemas found"
                    dataSource={databaseSchema}
                    columns={[
                        {
                            title: 'Table',
                            key: 'table',
                            render: function RenderTable(_, schema) {
                                return schema.table
                            },
                        },
                        {
                            title: (
                                <>
                                    <span>Sync</span>
                                    <Link
                                        className="ml-2 w-[60px] overflow-visible"
                                        onClick={() => toggleAllSwitches()}
                                    >
                                        {toggleAllState ? 'Enable' : 'Disable'} all
                                    </Link>
                                </>
                            ),
                            key: 'should_sync',
                            render: function RenderShouldSync(_, schema) {
                                return (
                                    <LemonSwitch
                                        checked={schema.should_sync}
                                        onChange={(checked) => {
                                            toggleSchemaShouldSync(schema, checked)
                                        }}
                                    />
                                )
                            },
                        },
                        {
                            key: 'sync_type',
                            title: 'Sync type',
                            tooltip:
                                'Full refresh will refresh the full table on every sync, whereas incremental will only sync new and updated rows since the last sync',
                            render: (_, schema) => {
                                const options = syncTypesToOptions(schema)

                                return (
                                    <LemonSelect
                                        options={options}
                                        value={schema.sync_type}
                                        onChange={(newValue) => updateSchemaSyncType(schema, newValue)}
                                    />
                                )
                            },
                        },
                    ]}
                />
            </div>
        </div>
    )
}
