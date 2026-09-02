import { useMountedLogic } from 'kea'

import { customerTasksLogic } from './customerTasksLogic'
import { CustomerTasksTable } from './CustomerTasksTable'
export interface CustomerTasksInboxProps {
    persistFilters?: boolean
    persistenceKey?: string
    canViewAll?: boolean
}
export function CustomerTasksInbox({
    persistFilters = false,
    persistenceKey,
    canViewAll = false,
}: CustomerTasksInboxProps): JSX.Element {
    const logic = customerTasksLogic({
        context: 'inbox',
        persistInboxFilters: persistFilters,
        persistPrefix: persistenceKey,
    })
    useMountedLogic(logic)
    return <CustomerTasksTable logic={logic} context="inbox" canViewAll={canViewAll} />
}
