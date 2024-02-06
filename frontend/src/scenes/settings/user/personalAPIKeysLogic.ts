import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { PersonalAPIKeyType } from '~/types'

import type { personalAPIKeysLogicType } from './personalAPIKeysLogicType'

export const API_KEY_SCOPE_PRESETS = [
    // TODO: Double check scopes make sense
    { value: 'local_evaluation', label: 'Local feature flag evaluation', scopes: ['feature_flag:read'] },
    { value: 'analytics', label: 'Performing analytics queries', scopes: ['query:read'] },
    {
        value: 'project_management',
        label: 'Project & user management',
        scopes: ['team:write', 'organization:read', 'organization_member:write'],
    },
]

export type APIScope = {
    key: string
    actions: string[]
    description?: string
}

export const APIScopes: APIScope[] = [
    { key: 'action', actions: ['read', 'write'] },
    { key: 'activity_log', actions: ['read', 'write'] },
    { key: 'annotation', actions: ['read', 'write'] },
    { key: 'batch_export', actions: ['read', 'write'] },
    { key: 'cohort', actions: ['read', 'write'] },
    { key: 'dashboard', actions: ['read', 'write'] },
    { key: 'early_access_feature', actions: ['read', 'write'] },
    { key: 'event_definition', actions: ['read', 'write'] },
    { key: 'experiment', actions: ['read', 'write'] },
    { key: 'export', actions: ['read', 'write'] },
    { key: 'feature_flag', actions: ['read', 'write'] },
    { key: 'group', actions: ['read', 'write'] },
    { key: 'insight', actions: ['read', 'write'] },
    { key: 'query', actions: ['read'] },
    { key: 'notebook', actions: ['read', 'write'] },
    { key: 'organization', actions: ['read', 'write'] },
    { key: 'organization_member', actions: ['read', 'write'] },
    { key: 'person', actions: ['read', 'write'] },
    { key: 'plugin', actions: ['read', 'write'] },
    { key: 'property_definition', actions: ['read', 'write'] },
    { key: 'session_recording', actions: ['read', 'write'] },
    { key: 'session_recording_playlist', actions: ['read', 'write'] },
    { key: 'sharing_configuration', actions: ['read', 'write'] },
    { key: 'subscription', actions: ['read', 'write'] },
    { key: 'survey', actions: ['read', 'write'] },
    { key: 'team', actions: ['read', 'write'] },
    // { key: 'uploaded_media', actions: ['read', 'write'] },
    { key: 'user', actions: ['read', 'write'] },
    { key: 'data_warehouse_table', actions: ['read', 'write'] },
    { key: 'scheduled_change', actions: ['read', 'write'] },
]

export const personalAPIKeysLogic = kea<personalAPIKeysLogicType>([
    path(['lib', 'components', 'PersonalAPIKeys', 'personalAPIKeysLogic']),
    actions({
        setEditingKeyId: (id: PersonalAPIKeyType['id'] | null) => ({ id }),
        loadKeys: true,
        createKey: (label: string) => ({ label }),
        updateKey: (data: Partial<Pick<PersonalAPIKeyType, 'label' | 'scopes'>>) => data,
        deleteKey: (id: PersonalAPIKeyType['id']) => ({ id }),
        setScopeRadioValue: (key: string, action: string) => ({ key, action }),
    }),

    reducers({
        editingKeyId: [
            null as PersonalAPIKeyType['id'] | null,
            {
                setEditingKeyId: (_, { id }) => id,
            },
        ],
    }),
    loaders(({ values }) => ({
        keys: [
            [] as PersonalAPIKeyType[],
            {
                loadKeys: async () => {
                    return await api.personalApiKeys.list()
                },
                deleteKey: async ({ id }) => {
                    await api.personalApiKeys.delete(id)
                    await api.delete(`api/personal_api_keys/${id}/`)
                    return values.keys.filter((filteredKey) => filteredKey.id != id)
                },
            },
        ],
    })),
    forms(({ values, actions }) => ({
        editingKey: {
            defaults: { label: '', scopes: [] } as Pick<PersonalAPIKeyType, 'label' | 'scopes'> & { preset?: string },
            errors: ({ label, scopes }) => ({
                label: !label ? 'Your API key needs a label' : undefined,
                scopes: !scopes?.length ? ('Your API key needs at least one scope' as any) : undefined,
            }),
            submit: async (payload, breakpoint) => {
                if (!values.editingKeyId) {
                    return
                }

                const key =
                    values.editingKeyId === 'new'
                        ? await api.personalApiKeys.create(payload)
                        : await api.personalApiKeys.update(values.editingKeyId, payload)

                breakpoint()

                lemonToast.success(`Personal API Key saved.`)

                actions.loadKeysSuccess([key].concat(values.keys.filter((k) => k.id !== values.editingKeyId)))
                actions.setEditingKeyId(null)
            },
        },
    })),
    selectors(() => ({
        formScopeRadioValues: [
            (s) => [s.editingKey],
            (editingKey): Record<string, string> => {
                const result: Record<string, string> = {}

                editingKey.scopes.forEach((scope) => {
                    const [key, action] = scope.split(':')
                    result[key] = action
                })

                return result
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        setEditingKeyValue: async ({ name, value }) => {
            const key = Array.isArray(name) ? name[0] : name
            // When we select a preset, update the scopes
            if (key === 'preset' && value) {
                const preset = API_KEY_SCOPE_PRESETS.find((preset) => preset.value === value)
                if (preset) {
                    actions.setEditingKeyValue('scopes', preset.scopes)
                }
            }

            // When the user deviates from the preset, clear it
            if (key === 'scopes' && values.editingKey.preset) {
                const preset = API_KEY_SCOPE_PRESETS.find((preset) => preset.value === values.editingKey.preset)
                if (preset?.scopes.join(',') !== value.join(',')) {
                    actions.setEditingKeyValue('preset', undefined)
                }
            }
        },

        setEditingKeyId: async ({ id }) => {
            if (id) {
                const key = values.keys.find((key) => key.id === id)
                actions.resetEditingKey({
                    label: key?.label ?? '',
                    scopes: key?.scopes ?? [],
                })
            }
        },

        setScopeRadioValue: ({ key, action }) => {
            const newScopes = values.editingKey.scopes.filter((scope) => !scope.startsWith(key))
            if (action !== 'none') {
                newScopes.push(`${key}:${action}`)
            }

            actions.setEditingKeyValue('scopes', newScopes)
        },

        createKeySuccess: async ({ keys }: { keys: PersonalAPIKeyType[] }) => {
            keys[0]?.value && (await copyToClipboard(keys[0].value, 'personal API key value'))
        },
        deleteKeySuccess: () => {
            lemonToast.success(`Personal API key deleted`)
        },
    })),
])
