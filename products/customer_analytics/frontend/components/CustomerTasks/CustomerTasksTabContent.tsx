import { useMountedLogic } from 'kea'

import type { AccountViewTileLogicProps } from '../Accounts/accountViewTileConfig'
import { customerTasksLogic } from './customerTasksLogic'
import { CustomerTasksTable } from './CustomerTasksTable'
export interface CustomerTasksTabContentProps extends AccountViewTileLogicProps {
    accountId: string
    canCreate?: boolean
    canViewAll?: boolean
    embedded?: boolean
}
export function CustomerTasksTabContent({
    accountId,
    canCreate = false,
    canViewAll = false,
    embedded = true,
    ...tileProps
}: CustomerTasksTabContentProps): JSX.Element {
    const logic = customerTasksLogic({ context: 'account', accountId, ...tileProps })
    useMountedLogic(logic)
    return (
        <CustomerTasksTable
            logic={logic}
            context="account"
            canCreate={canCreate}
            canViewAll={canViewAll}
            embedded={embedded}
        />
    )
}
