import { useMountedLogic, useValues } from 'kea'

import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { customerTasksPersistencePrefix } from './customerTaskFilters'
import { customerTasksLogic } from './customerTasksLogic'
import { CustomerTasksTable } from './CustomerTasksTable'
export interface CustomerTasksInboxProps {
    canCreate?: boolean
    canViewAll?: boolean
}
export function CustomerTasksInbox({ canCreate = false, canViewAll = false }: CustomerTasksInboxProps): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const persistPrefix =
        currentTeamId !== null && user?.id !== undefined
            ? customerTasksPersistencePrefix(currentTeamId, user.id)
            : undefined
    const logic = customerTasksLogic({
        context: 'inbox',
        canViewAll,
        persistPrefix,
    })
    useMountedLogic(logic)
    return <CustomerTasksTable logic={logic} context="inbox" canCreate={canCreate} canViewAll={canViewAll} />
}
