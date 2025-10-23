import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { ProjectSecretAPIKeyRequest } from 'src/queries/schema/schema-general'

import { LemonDialog } from '@posthog/lemon-ui'

import api from 'lib/api'
import { CodeSnippet } from 'lib/components/CodeSnippet'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { PROJECT_SECRET_API_KEY_SCOPES, PROJECT_SECRET_API_KEY_SCOPE_PRESETS } from 'lib/scopes'
import { teamLogic } from 'scenes/teamLogic'

import { ProjectSecretAPIKeyType } from '~/types'

import type { projectAPIKeysLogicType } from './projectAPIKeysLogicType'

export type EditingProjectKeyFormValues = ProjectSecretAPIKeyRequest & {
    preset?: string
}

export const MAX_PROJECT_API_KEYS_PER_PROJECT = 10

export const projectAPIKeysLogic = kea<projectAPIKeysLogicType>([
    path(['scenes', 'settings', 'project', 'projectAPIKeysLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),

    actions({
        setEditingKeyId: (id: ProjectSecretAPIKeyType['id'] | null) => ({ id }),
        loadKeys: true,
        createKeySuccess: (key: ProjectSecretAPIKeyType) => ({ key }),
        showRollKeySuccessDialog: (key: ProjectSecretAPIKeyType) => ({ key }),
        deleteKey: (id: ProjectSecretAPIKeyType['id']) => ({ id }),
        rollKey: (id: ProjectSecretAPIKeyType['id']) => ({ id }),
        setScopeRadioValue: (key: string, action: string) => ({ key, action }),
        resetScopes: true,
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
    }),

    reducers({
        editingKeyId: [
            null as ProjectSecretAPIKeyType['id'] | null,
            {
                setEditingKeyId: (_, { id }) => id,
            },
        ],
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
                setEditingKeyId: () => '',
            },
        ],
    }),

    loaders(({ values, actions }) => ({
        keys: [
            [] as ProjectSecretAPIKeyType[],
            {
                loadKeys: async () => {
                    if (!values.currentTeamId) {
                        return []
                    }
                    try {
                        return await api.projectSecretApiKeys.list()
                    } catch (error: any) {
                        lemonToast.error('Failed to load project API keys')
                        throw error
                    }
                },
                deleteKey: async ({ id }: { id: string }) => {
                    try {
                        await api.projectSecretApiKeys.delete(id)
                        lemonToast.success('Project API key deleted')
                        return values.keys.filter((key: ProjectSecretAPIKeyType) => key.id !== id)
                    } catch (error: any) {
                        lemonToast.error('Failed to delete project API key')
                        throw error
                    }
                },
                rollKey: async ({ id }: { id: string }) => {
                    const origKey = values.keys.find((key: ProjectSecretAPIKeyType) => key.id === id)
                    if (!origKey) {
                        return values.keys
                    }

                    try {
                        const rolledKey = await api.projectSecretApiKeys.roll(id)
                        actions.showRollKeySuccessDialog(rolledKey)

                        rolledKey.value = undefined
                        return values.keys.map((key: ProjectSecretAPIKeyType) => (key.id === id ? rolledKey : key))
                    } catch (error: any) {
                        lemonToast.error('Failed to roll project API key')
                        throw error
                    }
                },
            },
        ],
    })),

    forms(({ values, actions }) => ({
        editingKey: {
            defaults: {
                label: '',
                scopes: [],
                preset: undefined,
            } as EditingProjectKeyFormValues,
            errors: ({ label, scopes }) => ({
                label: !label ? 'Your API key needs a label' : undefined,
                scopes: !scopes?.length ? ('Your API key needs at least one scope' as any) : undefined,
            }),
            submit: async (payload, breakpoint) => {
                if (!values.editingKeyId || !values.currentTeamId) {
                    return
                }

                try {
                    // Remove preset from payload as it's frontend-only
                    const { preset, ...apiPayload } = payload

                    const key =
                        values.editingKeyId === 'new'
                            ? await api.projectSecretApiKeys.create(apiPayload)
                            : await api.projectSecretApiKeys.update(values.editingKeyId, apiPayload)

                    breakpoint()

                    if (values.editingKeyId === 'new') {
                        actions.createKeySuccess(key)
                    } else {
                        lemonToast.success('Project API key updated')
                    }

                    actions.loadKeysSuccess([
                        key,
                        ...values.keys.filter((k: ProjectSecretAPIKeyType) => k.id !== values.editingKeyId),
                    ])
                    actions.setEditingKeyId(null)
                } catch (error: any) {
                    lemonToast.error('Failed to save project API key')
                    throw error
                }
            },
        },
    })),

    selectors(() => ({
        formScopeRadioValues: [
            (s) => [s.editingKey],
            (editingKey: EditingProjectKeyFormValues): Record<string, string> => {
                const result: Record<string, string> = {}
                editingKey.scopes?.forEach((scope: string) => {
                    const [key, action] = scope.split(':')
                    result[key] = action
                })
                return result
            },
        ],
        filteredScopes: [
            (s) => [s.searchTerm],
            (searchTerm: string) => {
                if (!searchTerm.trim()) {
                    return PROJECT_SECRET_API_KEY_SCOPES
                }
                const lowerSearch = searchTerm.toLowerCase()
                return PROJECT_SECRET_API_KEY_SCOPES.filter(({ key }) =>
                    key.replace(/_/g, ' ').toLowerCase().includes(lowerSearch)
                )
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        setEditingKeyValue: async ({ name, value }) => {
            const key = Array.isArray(name) ? name[0] : name

            if (key === 'preset' && value) {
                const preset = PROJECT_SECRET_API_KEY_SCOPE_PRESETS.find((p) => p.value === value)
                if (preset) {
                    actions.setEditingKeyValue('scopes', preset.scopes)
                }
            }

            if (key === 'scopes' && values.editingKey.preset) {
                const preset = PROJECT_SECRET_API_KEY_SCOPE_PRESETS.find((p) => p.value === values.editingKey.preset)
                if (preset?.scopes.join(',') !== value.join(',')) {
                    actions.setEditingKeyValue('preset', undefined)
                }
            }
        },

        setEditingKeyId: ({ id }: { id: string | null }) => {
            if (id) {
                const key = values.keys.find((k: ProjectSecretAPIKeyType) => k.id === id)
                actions.resetEditingKey({
                    label: key?.label ?? '',
                    scopes: key?.scopes ?? [],
                    preset: undefined,
                })
            }
        },

        setScopeRadioValue: ({ key, action }: { key: string; action: string }) => {
            const newScopes = (values.editingKey.scopes || []).filter((s: string) => !s.startsWith(key))
            if (action !== 'none') {
                newScopes.push(`${key}:${action}`)
            }
            actions.setEditingKeyValue('scopes', newScopes)
        },

        resetScopes: () => {
            actions.setEditingKeyValue('scopes', [])
        },

        createKeySuccess: ({ key }) => {
            if (!key.value) {
                return
            }

            LemonDialog.open({
                title: 'Project API key ready',
                width: 536,
                content: (
                    <>
                        <p>Copy your new project API key:</p>
                        <CodeSnippet thing="project API key">{key.value}</CodeSnippet>
                        <p className="text-warning mt-4">
                            <strong>Warning:</strong> This key will never be shown again. Copy it now.
                        </p>
                    </>
                ),
            })
        },

        showRollKeySuccessDialog: ({ key }) => {
            if (!key.value) {
                return
            }

            LemonDialog.open({
                title: 'Project API key rolled',
                width: 536,
                content: (
                    <>
                        <p>Your new key for "{key.label}":</p>
                        <CodeSnippet thing="project API key">{key.value}</CodeSnippet>
                        <p className="text-warning mt-4">
                            <strong>Warning:</strong> The previous key is no longer valid. This key will never be shown
                            again. Copy it now.
                        </p>
                    </>
                ),
            })
        },
    })),

    afterMount(({ actions }) => {
        actions.loadKeys()
    }),
])
