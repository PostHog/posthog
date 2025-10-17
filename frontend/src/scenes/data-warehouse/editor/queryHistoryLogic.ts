import { connect, kea, path, props } from 'kea'

import { activityLogLogic } from 'lib/components/ActivityLog/activityLogLogic'

import { ActivityScope } from '~/types'

import type { queryHistoryLogicType } from './queryHistoryLogicType'

export type QueryHistoryLogicProps = {
    id: string
}

export const queryHistoryLogic = kea<queryHistoryLogicType>([
    path(['scenes', 'data-warehouse', 'editor', 'queryHistoryLogic']),
    props({} as QueryHistoryLogicProps),
    connect(({ id }: QueryHistoryLogicProps) => ({
        values: [
            activityLogLogic({ scope: ActivityScope.DATA_WAREHOUSE_SAVED_QUERY, id: id }),
            ['humanizedActivity', 'activityLoading', 'pagination'],
        ],
    })),
])
