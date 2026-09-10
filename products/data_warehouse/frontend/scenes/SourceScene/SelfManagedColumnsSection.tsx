import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { DatabaseTable } from 'scenes/data-management/database/DatabaseTable'
import { dataWarehouseSettingsSceneLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsSceneLogic'

import { AccessControlLevel, AccessControlResourceType, DataWarehouseTable } from '~/types'

export function SelfManagedColumnsSection({ table }: { table: DataWarehouseTable }): JSX.Element {
    const {
        database,
        databaseLoading,
        databaseLoadError,
        dataWarehouseTables,
        selectedRow,
        inEditSchemaMode,
        editSchemaIsLoading,
    } = useValues(dataWarehouseSettingsSceneLogic)
    const {
        selectRow,
        toggleEditSchemaMode,
        updateSelectedSchema,
        saveSchema,
        cancelEditSchema,
        refreshDatabaseSchema,
    } = useActions(dataWarehouseSettingsSceneLogic)

    const schemaTable = dataWarehouseTables.find(({ id }) => id === table.id)

    // The type dropdowns render from `selectedRow`, and `saveSchema` reads the table id off it, so
    // this table has to be the selected row before the editor can do anything.
    useEffect(() => {
        if (!schemaTable || selectedRow === schemaTable) {
            return
        }
        // The schema store hands out a new table object when it hydrates that table's fields, and
        // `selectedRow` does not follow, so this compares the object rather than the id. An open
        // edit of the same table keeps the row it started on, because the pending types live there.
        if (inEditSchemaMode && selectedRow?.id === schemaTable.id) {
            return
        }
        selectRow(schemaTable)
    }, [schemaTable, selectedRow, inEditSchemaMode, selectRow])

    // Edit mode and the pending types live in a logic that outlives this page, so without this a
    // half-finished edit comes back on the next visit.
    useEffect(() => () => cancelEditSchema(), [cancelEditSchema])

    if (!schemaTable) {
        // A failed schema query leaves `database` at null, so without this the section would hold a
        // skeleton that never resolves.
        if (databaseLoadError) {
            return (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: () => refreshDatabaseSchema() }}>
                    Couldn't load this table's columns.
                </LemonBanner>
            )
        }

        // `dataWarehouseTables` is empty for the whole of any schema load, including the refresh
        // after a save, so "no columns" is only true once a load has landed.
        return databaseLoading || !database ? (
            <LemonSkeleton className="w-full h-32" />
        ) : (
            <p className="text-secondary">
                PostHog hasn't read this table's columns yet. Check the file URL pattern and credentials above.
            </p>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-row flex-wrap justify-between items-center gap-2">
                <h2 className="text-base font-semibold mb-0">Columns</h2>
                {inEditSchemaMode ? (
                    <div className="flex flex-row flex-wrap gap-2">
                        <LemonButton type="primary" loading={editSchemaIsLoading} onClick={() => saveSchema()}>
                            Save types
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            disabledReason={editSchemaIsLoading ? 'Wait for the save to finish' : undefined}
                            onClick={() => cancelEditSchema()}
                        >
                            Cancel
                        </LemonButton>
                    </div>
                ) : (
                    <AccessControlAction
                        resourceType={AccessControlResourceType.WarehouseTable}
                        minAccessLevel={AccessControlLevel.Editor}
                        userAccessLevel={table.user_access_level}
                    >
                        <LemonButton
                            type="secondary"
                            onClick={() => toggleEditSchemaMode(true)}
                            data-attr="self-managed-edit-column-types"
                        >
                            Edit column types
                        </LemonButton>
                    </AccessControlAction>
                )}
            </div>
            <p className="text-sm text-secondary mb-0">
                PostHog reads each column with the type shown here. Change a type when a column comes back wrong, for
                example a number stored as a string.
            </p>
            <DatabaseTable
                table={schemaTable.name}
                tables={[selectedRow?.id === schemaTable.id ? selectedRow : schemaTable]}
                inEditSchemaMode={inEditSchemaMode}
                schemaOnChange={updateSelectedSchema}
            />
        </div>
    )
}
