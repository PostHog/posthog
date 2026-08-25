import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonModal,
    LemonSearchableSelect,
    LemonTag,
    Spinner,
} from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { publishedTablesLogic } from './publishedTablesLogic'

export function PublishTableModal(): JSX.Element {
    const {
        publishModalOpen,
        publishTable,
        selectedSchemaDisabledReason,
        selectedSchemaTables,
        selectedWarehouseTable,
        warehouseSchemas,
        warehouseTables,
        warehouseTablesLoading,
        warehouseTablesError,
        isPublishTableSubmitting,
    } = useValues(publishedTablesLogic)
    const { closePublishModal, loadWarehouseTables, submitPublishTable } = useActions(publishedTablesLogic)

    const noWarehouseTables = warehouseTables !== null && warehouseTables.length === 0

    return (
        <LemonModal
            isOpen={publishModalOpen}
            title="Publish a warehouse table"
            description="Create a snapshot that can be queried with other warehouse data in PostHog."
            onClose={closePublishModal}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closePublishModal}
                        disabled={isPublishTableSubmitting}
                        data-attr="cancel-publish-table"
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitPublishTable}
                        loading={isPublishTableSubmitting}
                        data-attr="submit-publish-table"
                        disabledReason={
                            warehouseTablesLoading
                                ? 'Warehouse tables are still loading'
                                : warehouseTablesError
                                  ? 'Reload warehouse tables before publishing'
                                  : noWarehouseTables
                                    ? 'No warehouse tables are available to publish'
                                    : !publishTable.sourceSchemaName
                                      ? 'Select a schema'
                                      : !publishTable.sourceTableName
                                        ? 'Select a table'
                                        : selectedWarehouseTable?.disabled_reason || undefined
                        }
                    >
                        Publish table
                    </LemonButton>
                </>
            }
        >
            <Form logic={publishedTablesLogic} formKey="publishTable" className="flex flex-col gap-4">
                {warehouseTablesError ? (
                    <LemonBanner type="error" action={{ children: 'Try again', onClick: loadWarehouseTables }}>
                        {warehouseTablesError}
                    </LemonBanner>
                ) : null}
                <LemonField name="sourceSchemaName" label="Schema">
                    {warehouseTablesLoading || warehouseTables === null ? (
                        <div className="flex min-h-10 items-center gap-2 text-muted">
                            <Spinner />
                            <span>Loading warehouse tables...</span>
                        </div>
                    ) : (
                        <LemonSearchableSelect
                            fullWidth
                            placeholder="Select a schema"
                            searchPlaceholder="Search schemas"
                            noResultsMessage="No schemas match your search."
                            options={warehouseSchemas.map((schema) => ({
                                value: schema.name,
                                label: schema.name,
                                labelInMenu: (
                                    <div className="flex w-full items-center justify-between gap-2">
                                        <span>{schema.name}</span>
                                        {schema.managed ? <LemonTag type="muted">Managed</LemonTag> : null}
                                    </div>
                                ),
                            }))}
                        />
                    )}
                </LemonField>
                {selectedSchemaDisabledReason ? (
                    <LemonBanner type="info">{selectedSchemaDisabledReason}</LemonBanner>
                ) : null}
                <LemonField name="sourceTableName" label="Table">
                    <LemonSearchableSelect
                        fullWidth
                        placeholder={publishTable.sourceSchemaName ? 'Select a table' : 'Select a schema first'}
                        searchPlaceholder="Search tables"
                        noResultsMessage="No tables match your search."
                        disabledReason={publishTable.sourceSchemaName ? undefined : 'Select a schema first'}
                        options={selectedSchemaTables.map((table) => ({
                            value: table.table_name,
                            label: table.table_name,
                            disabledReason: table.disabled_reason || undefined,
                        }))}
                    />
                </LemonField>
                <LemonField
                    name="name"
                    label="Table name in PostHog"
                    info="Leave blank to generate a name from the schema and table."
                >
                    <LemonInput placeholder="modeled_customers" />
                </LemonField>
            </Form>
        </LemonModal>
    )
}
