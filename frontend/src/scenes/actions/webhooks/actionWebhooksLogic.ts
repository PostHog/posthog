import { afterMount, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { toParams } from 'lib/utils'

import { ActionType, HookConfigType } from '~/types'

import type { actionWebhooksLogicType } from './actionWebhooksLogicType'

export const actionWebhooksLogic = kea<actionWebhooksLogicType>([
    props({} as { id: ActionType['id'] }),
    key((props) => `${props.id}`),
    path(['scenes', 'actions', 'actionWebhooksLogic']),
    path((key) => ['scenes', 'actions', 'actionWebhooksLogic', key]),
    loaders(({ props }) => ({
        actionWebhooks: [
            null as HookConfigType[] | null,
            {
                loadActionWebhooks: async () => {
                    return api.loadPaginatedResults<HookConfigType>(
                        'api/projects/@current/hooks?' +
                            toParams({
                                resource_id: props.id,
                            })
                    )
                },
            },
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadActionWebhooks()
    }),
])
