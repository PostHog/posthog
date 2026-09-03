import { useMountedLogic } from 'kea'

import { customerTasksLogic } from './customerTasksLogic'
import { CustomerTasksTable } from './CustomerTasksTable'
export interface CustomerTasksTabContentProps {
    accountId: string
    canCreate?: boolean
    canViewAll?: boolean
}
export function CustomerTasksTabContent({
    accountId,
    canCreate = false,
    canViewAll = false,
}: CustomerTasksTabContentProps): JSX.Element {
    const logic = customerTasksLogic({ context: 'account', accountId })
    useMountedLogic(logic)
    return <CustomerTasksTable logic={logic} context="account" canCreate={canCreate} canViewAll={canViewAll} />
}
