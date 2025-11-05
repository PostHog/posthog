import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { LemonDialog } from '@posthog/lemon-ui'

import api, { PaginatedResponse } from 'lib/api'
import { CodeSnippet } from 'lib/components/CodeSnippet'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import type { teamSecretKeysLogicType } from './teamSecretKeysLogicType'

export const MAX_SECRET_KEYS_PER_TEAM = 20

export interface TeamSecretKeyType {
    id: string
    name: string
    value?: string | null
    mask_value: string
    created_at: string
    last_used_at: string | null
    created_by: {
        id: number
        email: string
        first_name: string
    } | null
}

export type EditingKeyFormValues = Pick<TeamSecretKeyType, 'name'>

export const teamSecretKeysLogic = kea<teamSecretKeysLogicType>([
    path(['scenes', 'settings', 'environment', 'teamSecretKeysLogic']),
    actions({
        setEditingKeyId: (id: TeamSecretKeyType['id'] | null) => ({ id }),
        loadKeys: true,
        createKeySuccess: (key: TeamSecretKeyType) => ({ key }),
        showCreateKeySuccessDialog: (key: TeamSecretKeyType) => ({ key }),
        deleteKey: (id: TeamSecretKeyType['id']) => ({ id }),
    }),

    reducers({
        editingKeyId: [
            null as TeamSecretKeyType['id'] | null,
            {
                setEditingKeyId: (_, { id }) => id,
            },
        ],
    }),

    loaders(({ values }) => ({
        keys: [
            [] as TeamSecretKeyType[],
            {
                loadKeys: async () => {
                    const response: PaginatedResponse<TeamSecretKeyType> = await api.get(
                        `api/environments/@current/secret_keys/`
                    )
                    return response.results || []
                },
                deleteKey: async ({ id }) => {
                    await api.delete(`api/environments/@current/secret_keys/${id}/`)
                    lemonToast.success('Secret key deleted')
                    return values.keys.filter((filteredKey: TeamSecretKeyType) => filteredKey.id !== id)
                },
            },
        ],
    })),

    forms(({ values, actions }) => ({
        editingKey: {
            defaults: {
                name: '',
            } as EditingKeyFormValues,
            errors: ({ name }) => ({
                name: !name ? 'Your secret key needs a name' : undefined,
            }),
            submit: async (payload, breakpoint) => {
                if (!values.editingKeyId) {
                    return
                }

                const key: TeamSecretKeyType = await api.create(`api/environments/@current/secret_keys/`, payload)

                breakpoint()

                if (values.editingKeyId === 'new') {
                    actions.createKeySuccess(key)
                }

                actions.loadKeysSuccess([key].concat(values.keys))
                actions.setEditingKeyId(null)
            },
        },
    })),

    listeners(({ actions }) => ({
        createKeySuccess: ({ key }) => {
            actions.showCreateKeySuccessDialog(key)
        },
        showCreateKeySuccessDialog: ({ key }) => {
            LemonDialog.open({
                title: 'Secret key created',
                width: '40rem',
                primaryButton: {
                    children: 'I have saved it',
                    type: 'primary',
                },
                content: (
                    <div className="space-y-2">
                        <div>
                            <b>This is the only time you will see this key.</b> Save it somewhere safe.
                        </div>
                        <CodeSnippet className="ph-no-capture" thing="secret key">
                            {key.value || ''}
                        </CodeSnippet>
                    </div>
                ),
            })
        },
    })),

    afterMount(({ actions }) => {
        actions.loadKeys()
    }),
])
