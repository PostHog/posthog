import { BindLogic, useActions, useValues } from 'kea'

import { DataWarehouseTable } from '~/types'

import { SelfManagedSourceForm } from 'products/data_warehouse/frontend/scenes/NewSourceScene/components/SelfManagedSourceForm'
import { selfManagedSourceLogic } from 'products/data_warehouse/frontend/scenes/NewSourceScene/selfManagedSourceLogic'

interface SelfManagedProps {
    id: string
}

export const DataPipelinesSelfManagedSource = ({ id }: SelfManagedProps): JSX.Element => {
    const { table } = useValues(selfManagedSourceLogic({ id }))
    const { updateTable } = useActions(selfManagedSourceLogic({ id }))

    return (
        <BindLogic logic={selfManagedSourceLogic} props={{ id }}>
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
                <SelfManagedSourceForm
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
