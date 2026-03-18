import { BindLogic, useActions, useValues } from 'kea'

import { DatawarehouseTableForm } from 'scenes/data-warehouse/new/DataWarehouseTableForm'
import { dataWarehouseTableLogic } from 'scenes/data-warehouse/new/dataWarehouseTableLogic'

import { DataWarehouseTable } from '~/types'

interface SelfManagedProps {
    id: string
}

export const DataPipelinesSelfManagedSource = ({ id }: SelfManagedProps): JSX.Element => {
    const { table } = useValues(dataWarehouseTableLogic({ id }))
    const { updateTable } = useActions(dataWarehouseTableLogic({ id }))

    return (
        <BindLogic logic={dataWarehouseTableLogic} props={{ id }}>
            <DataPipelinesSelfManagedSourceTable table={table} updateTable={updateTable} />
        </BindLogic>
    )
}

interface Props {
    table: DataWarehouseTable
    updateTable: (tablePayload: any) => void
}

export function DataPipelinesSelfManagedSourceTable({ table, updateTable }: Props): JSX.Element {
    return (
        <>
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
