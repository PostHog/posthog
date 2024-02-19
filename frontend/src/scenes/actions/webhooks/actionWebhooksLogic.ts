import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, kea, key, path, props } from 'kea'
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
    actions({
        createActionWebhook: (hook: Pick<HookConfigType, 'target' | 'format_text'>) => ({ hook }),
        updateActionWebhook: (hook: Pick<HookConfigType, 'id' | 'target' | 'format_text'>) => ({ hook }),
        deleteActionWebhook: (hook: HookConfigType) => ({ hook }),
    }),
    loaders(({ props, actions, values }) => ({
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
                createActionWebhook: async ({ hook }) => {
                    const newHook = await api.create(`api/projects/@current/hooks`, hook)

                    return [...(values.actionWebhooks ?? []), newHook]
                },

                updateActionWebhook: async ({ hook }) => {
                    const { id, ...rest } = hook
                    const newHook = await api.update(`api/projects/@current/hooks/${id}`, rest)

                    return values.actionWebhooks?.map((x) => (x.id === id ? newHook : x)) ?? null
                },

                deleteActionWebhook: async ({ hook }) => {
                    await api.delete(`api/projects/@current/hooks/${hook.id}`)

                    lemonToast.success('Webhook deleted', {
                        button: {
                            label: 'Undo',
                            action: () => actions.createActionWebhook({ ...hook }),
                        },
                    })

                    return values.actionWebhooks?.filter((x) => x.id !== hook.id) ?? null
                },
            },
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadActionWebhooks()
    }),
])
