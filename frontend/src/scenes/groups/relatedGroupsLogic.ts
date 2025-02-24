import { actions, connect, events, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

import { ActorType } from '~/types'

import type { relatedGroupsLogicType } from './relatedGroupsLogicType'

export const relatedGroupsLogic = kea<relatedGroupsLogicType>([
    props(
        {} as {
            groupTypeIndex: number | null
            id: string
        }
    ),
    key((props) => `${props.groupTypeIndex ?? 'person'}-${props.id}`),
    path(['scenes', 'groups', 'relatedGroupsLogic']),
    connect({ values: [teamLogic, ['currentTeamId']] }),
    actions(() => ({
        loadRelatedActors: true,
    })),
    loaders(({ values, props }) => ({
        relatedActors: [
            [] as ActorType[],
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
    })),
    events(({ actions }) => ({
        afterMount: actions.loadRelatedActors,
    })),
])
