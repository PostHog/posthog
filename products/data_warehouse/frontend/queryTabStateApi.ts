import { getCurrentTeamId } from 'lib/utils/getAppContext'

import { QueryTabState } from '~/types'

import { queryTabStatePartialUpdate, queryTabStateUserRetrieve } from './generated/api'

const projectId = (): string => String(getCurrentTeamId())

export const queryTabStateApi = {
    async user(userId: string): Promise<QueryTabState> {
        return (await queryTabStateUserRetrieve(projectId(), { user_id: userId })) as unknown as QueryTabState
    },
    async update(id: string, data: Partial<QueryTabState>): Promise<QueryTabState> {
        return (await queryTabStatePartialUpdate(
            projectId(),
            id,
            data as Parameters<typeof queryTabStatePartialUpdate>[2]
        )) as unknown as QueryTabState
    },
}
