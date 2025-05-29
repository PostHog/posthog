import { LemonButton } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { DatawarehouseTableForm } from 'scenes/data-warehouse/new/DataWarehouseTableForm'
import { dataWarehouseTableLogic } from 'scenes/data-warehouse/new/dataWarehouseTableLogic'
import { urls } from 'scenes/urls'

import { DataWarehouseTable } from '~/types'

interface SelfManagedProps {
    id: string
}

export const DataPipelinesSelfManagedSource = ({ id }: SelfManagedProps): JSX.Element => {
    const { table } = useValues(dataWarehouseTableLogic({ id }))
    const { updateTable, editingTable } = useActions(dataWarehouseTableLogic({ id }))

    return (
        <BindLogic logic={dataWarehouseTableLogic} props={{ id }}>
            <DataPipelinesSelfManagedSourceTable table={table} updateTable={updateTable} editingTable={editingTable} />
        </BindLogic>
    )
}

interface Props {
    table: DataWarehouseTable
    updateTable: (tablePayload: any) => void
    editingTable: (editing: boolean) => void
}

export function DataPipelinesSelfManagedSourceTable({ table, updateTable, editingTable }: Props): JSX.Element {
    return (
        <>
            <PageHeader
                buttons={
                    <LemonButton
                        type="secondary"
                        onClick={() => {
                            editingTable(false)
                            router.actions.push(urls.pipeline())
                        }}
                    >
                        Cancel
                    </LemonButton>
                }
            />
            <div className="deprecated-space-y-4">
                <DatawarehouseTableForm
                    onUpdate={() =>
                        updateTable({
                            name: table.name,
                            url_pattern: table.url_pattern,
                            format: table.format,
                            ...(table.credential?.access_key || table.credential?.access_secret
                                ? {
                                      credential: {
                                          ...(table.credential.access_key
                                              ? { access_key: table.credential.access_key }
                                              : {}),
                                          ...(table.credential.access_secret
                                              ? { access_secret: table.credential.access_secret }
                                              : {}),
                                      },
                                  }
                                : {}),
                        })
                    }
                />
            </div>
        </>
    )
}
