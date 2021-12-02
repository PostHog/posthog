import { kea } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { RelatedActor } from '~/types'

import { relatedGroupsLogicType } from './relatedGroupsLogicType'
export const relatedGroupsLogic = kea<relatedGroupsLogicType>({
    path: ['scenes', 'groups', 'relatedGroupsLogic'],
    connect: { values: [teamLogic, ['currentTeamId']] },

    props: {} as {
        groupTypeIndex: number | null
        id: string
    },
    key: (props) => `${props.groupTypeIndex}-${props.id}`,

    actions: () => ({
        loadRelatedActors: true,
    }),
    loaders: ({ values, props }) => ({
        relatedActors: [
            [] as RelatedActor[],
            {
                loadRelatedActors: async () => {
                    const url = `api/projects/${values.currentTeamId}/groups/related?${toParams({
                        group_type_index: props.groupTypeIndex,
                        id: props.id,
                    })}`
                    return await api.get(url)
                },
                setGroup: () => [],
            },
        ],
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadRelatedActors,
    }),
})
