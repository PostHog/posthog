import { useMountedLogic } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'

import { AccessControlObject } from '~/layout/navigation-3000/sidepanel/panels/access_control/AccessControlObject'
import { AccessControlResourceType } from '~/types'

import { HistoryTableAccessSection } from 'products/data_warehouse/frontend/shared/components/HistoryTableAccessSection'
import { historyTableAccessLogic } from 'products/data_warehouse/frontend/shared/logics/historyTableAccessLogic'

export interface WarehouseTableAccessControlModalProps {
    isOpen: boolean
    onClose: () => void
    tableId: string
    title: string
    description: string
}

/** The access dialog of a warehouse table, with an offer to copy its rules to the table's history table. */
export function WarehouseTableAccessControlModal({
    isOpen,
    onClose,
    tableId,
    title,
    description,
}: WarehouseTableAccessControlModalProps): JSX.Element {
    useMountedLogic(historyTableAccessLogic({ tableId }))

    return (
        <LemonModal isOpen={isOpen} onClose={onClose} width="40rem" simple={false}>
            <AccessControlObject
                resource={AccessControlResourceType.WarehouseTable}
                resource_id={tableId}
                title={title}
                description={description}
            />
            <HistoryTableAccessSection tableId={tableId} />
        </LemonModal>
    )
}
