import { LemonButton } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { useEffect } from 'react'
import { DatawarehouseTableForm } from 'scenes/data-warehouse/new/DataWarehouseTableForm'
import { dataWarehouseTableLogic } from 'scenes/data-warehouse/new/dataWarehouseTableLogic'
import { urls } from 'scenes/urls'

import { DataWarehouseTable } from '~/types'

interface SelfManagedProps {
    id: string
}

export const SelfManaged = ({ id }: SelfManagedProps): JSX.Element => {
    const { table } = useValues(dataWarehouseTableLogic({ id: id }))
    const { loadTable, updateTable } = useActions(dataWarehouseTableLogic({ id: id }))

    useEffect(() => {
        loadTable()
    }, [loadTable])

    return (
        <BindLogic logic={dataWarehouseTableLogic} props={{ id }}>
            <SelfManagedTable table={table} updateTable={updateTable} />
        </BindLogic>
    )
}

interface Props {
    table: DataWarehouseTable
    updateTable: (tablePayload: any) => void
}

export function SelfManagedTable({ table, updateTable }: Props): JSX.Element {
    return (
        <>
            <PageHeader
                buttons={
                    <LemonButton
                        type="secondary"
                        onClick={() => {
                            router.actions.push(urls.dataWarehouse())
                        }}
                    >
                        Cancel
                    </LemonButton>
                }
            />
            <div className="space-y-4">
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
