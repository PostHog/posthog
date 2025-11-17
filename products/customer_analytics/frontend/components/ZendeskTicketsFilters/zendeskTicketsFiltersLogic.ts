import { actions, kea, key, path, props, reducers } from 'kea'

import type { zendeskTicketsFiltersLogicType } from './zendeskTicketsFiltersLogicType'

const DEFAULT_PRIORITY = 'all'
const DEFAULT_STATUS = 'all'
const DEFAULT_ORDER_BY = 'updated_at'
const DEFAULT_ORDER_DIRECTION = 'desc'

export interface ZendeskTicketsFiltersLogicProps {
    logicKey: string
}

export const zendeskTicketsFiltersLogic = kea<zendeskTicketsFiltersLogicType>([
    path(['products', 'customer_analytics', 'components', 'ZendeskTicketsFilters', 'zendeskTicketsFiltersLogic']),
    props({} as ZendeskTicketsFiltersLogicProps),
    key(({ logicKey }) => logicKey),

    actions({
        setOrderBy: (orderBy: string) => ({ orderBy }),
        setOrderDirection: (orderDirection: string) => ({ orderDirection }),
        setPriority: (priority: string) => ({ priority }),
        setStatus: (status: string) => ({ status }),
    }),

    reducers({
        priority: [
            DEFAULT_PRIORITY as string,
            {
                setPriority: (_, { priority }) => priority,
            },
        ],
        status: [
            DEFAULT_STATUS as string,
            {
                setStatus: (_, { status }) => status,
            },
        ],
        orderBy: [DEFAULT_ORDER_BY as string, { setOrderBy: (_, { orderBy }) => orderBy }],
        orderDirection: [
            DEFAULT_ORDER_DIRECTION as string,
            { setOrderDirection: (_, { orderDirection }) => orderDirection },
        ],
    }),
])
