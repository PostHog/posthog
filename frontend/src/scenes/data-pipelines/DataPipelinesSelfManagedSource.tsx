import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton } from '@posthog/lemon-ui'

import { DatawarehouseTableForm } from 'scenes/data-warehouse/new/DataWarehouseTableForm'
import { dataWarehouseTableLogic } from 'scenes/data-warehouse/new/dataWarehouseTableLogic'
import { urls } from 'scenes/urls'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { DataWarehouseTable } from '~/types'

interface SelfManagedProps {
    id: string
}

export const DataPipelinesSelfManagedSource = ({ id }: SelfManagedProps): JSX.Element => {
    const { table } = useValues(dataWarehouseTableLogic({ id }))
    const { updateTable, editingTable } = useActions(dataWarehouseTableLogic({ id }))

    return (
        <BindLogic logic={dataWarehouseTableLogic} props={{ id }}>
            <SceneTitleSection
                name={table.name}
                description={table.url_pattern}
                resourceType={{ type: 'data_pipeline' }}
                actions={
                    <LemonButton
                        type="secondary"
                        onClick={() => {
                            editingTable(false)
                            router.actions.push(urls.dataPipelines('sources'))
                        }}
                        size="small"
                    >
                        Cancel
                    </LemonButton>
                }
            />
            <DataPipelinesSelfManagedSourceTable table={table} updateTable={updateTable} editingTable={editingTable} />
        </BindLogic>
    )
}

interface Props {
    table: DataWarehouseTable
    updateTable: (tablePayload: any) => void
    editingTable: (editing: boolean) => void
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
