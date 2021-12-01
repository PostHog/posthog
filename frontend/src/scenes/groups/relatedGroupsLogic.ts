import { kea } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { RelatedActor } from '~/types'

import { relatedGroupsLogicType } from './relatedGroupsLogicType'
export const relatedGroupsLogic = kea<relatedGroupsLogicType>({
    path: ['scenes', 'groups', 'relatedGroupsLogic'],
    connect: { values: [teamLogic, ['currentTeamId']] },
    actions: () => ({
        loadRelatedActors: (groupTypeIndex: number | null, id: string) => ({ groupTypeIndex, id }),
    }),
    loaders: ({ values }) => ({
        relatedActors: [
            [] as RelatedActor[],
            {
                loadRelatedActors: async ({ groupTypeIndex, id }) => {
                    const url = `api/projects/${values.currentTeamId}/groups/related?${toParams({
                        group_type_index: groupTypeIndex,
                        id,
                    })}`
                    return await api.get(url)
                },
                setGroup: () => [],
            },
        ],
    }),
})
