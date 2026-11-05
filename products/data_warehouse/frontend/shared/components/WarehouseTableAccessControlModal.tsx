import { useMountedLogic } from 'kea'

import { AccessControlObjectModal } from '~/layout/navigation-3000/sidepanel/panels/access_control/AccessControlObjectModal'
import { AccessControlResourceType } from '~/types'

import { historyTableAccessLogic } from 'products/data_warehouse/frontend/shared/logics/historyTableAccessLogic'

export interface WarehouseTableAccessControlModalProps {
    isOpen: boolean
    onClose: () => void
    tableId: string
    title: string
    description: string
}

/** The access dialog of a warehouse table, which offers to repeat each change on the table's history table. */
export function WarehouseTableAccessControlModal({
    tableId,
    ...props
}: WarehouseTableAccessControlModalProps): JSX.Element {
    useMountedLogic(historyTableAccessLogic({ tableId }))

    return (
        <AccessControlObjectModal
            {...props}
            resource={AccessControlResourceType.WarehouseTable}
            resource_id={tableId}
        />
    )
}
