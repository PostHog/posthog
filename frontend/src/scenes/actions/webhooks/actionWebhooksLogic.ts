import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { beforeUnload } from 'kea-router'
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
        setEditingWebhookId: (id: HookConfigType['id'] | null) => ({ id }),
    }),
    reducers({
        editingWebhookId: [
            null as HookConfigType['id'] | null,
            {
                setEditingWebhookId: (_, { id }) => id,
            },
        ],
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

    forms(({ values, actions, props }) => ({
        editingWebhook: {
            defaults: {
                target: '',
                format_text: null,
            } as Pick<HookConfigType, 'target' | 'format_text'>,
            errors: ({ target }) => ({
                target: !target ? 'This field is required' : undefined,
            }),
            submit: async (payload) => {
                const data = { ...payload, event: 'action_performed', resource_id: props.id }
                try {
                    if (values.editingWebhookId === 'new') {
                        await api.create(`api/projects/@current/hooks`, data)
                    } else {
                        await api.update(`api/projects/@current/hooks/${values.editingWebhookId}`, data)
                    }
                } catch (err: any) {
                    if (err.attr) {
                        actions.setEditingWebhookManualErrors({
                            [err.attr]: err.detail,
                        })
                    } else {
                        lemonToast.error(err.detail)
                    }
                    return
                }

                actions.setEditingWebhookId(null)
                actions.loadActionWebhooks()
            },
        },
    })),

    listeners(({ actions, values }) => ({
        setEditingWebhookId: async ({ id }) => {
            if (id) {
                const webhook = values.actionWebhooks?.find((key) => key.id === id)

                actions.resetEditingWebhook(webhook)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadActionWebhooks()
    }),

    beforeUnload(({ values, actions }) => ({
        enabled: () => !!values.editingWebhookId && values.editingWebhookChanged,
        message: `Leave action?\nChanges to your webhook configuration will be discarded.`,
        onConfirm: () => actions.setEditingWebhookId(null),
    })),
])
