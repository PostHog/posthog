import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { LemonDialog } from '@posthog/lemon-ui'

import api from 'lib/api'
import { CodeSnippet } from 'lib/components/CodeSnippet'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import {
    PROJECT_SECRET_API_KEY_ALLOWED_API_SCOPE_ACTION,
    PROJECT_SECRET_API_KEY_SCOPE_PRESETS,
    ProjectSecretAPIKeyAllowedScope,
    ProjectSecretAPIKeyScopePreset,
} from 'lib/scopes'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { teamLogic } from 'scenes/teamLogic'

import { ProjectSecretAPIKeyApi } from '~/generated/core/api.schemas'
import { APIScopeAction, ProjectSecretAPIKeyRequest } from '~/types'

import type { projectSecretAPIKeysLogicType } from './projectSecretAPIKeysLogicType'

export type EditingProjectKeyFormValues = ProjectSecretAPIKeyRequest & {
    preset?: string
}

export const MAX_PROJECT_API_KEYS_PER_PROJECT = 10

// llm_gateway powers the new AI gateway here, so label it "AI gateway" (PAKs keep "LLM gateway").
const PROJECT_SECRET_SCOPE_OBJECT_NAMES: Record<string, string> = {
    llm_gateway: 'AI gateway',
}

export const projectSecretAPIKeysLogic = kea<projectSecretAPIKeysLogicType>([
    path(['scenes', 'settings', 'project', 'projectSecretAPIKeysLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeamId'], featureFlagLogic, ['featureFlags']],
    })),

    actions({
        setEditingKeyId: (id: ProjectSecretAPIKeyApi['id'] | null) => ({ id }),
        loadKeys: true,
        createKeySuccess: (key: ProjectSecretAPIKeyApi) => ({ key }),
        showRollKeySuccessDialog: (key: ProjectSecretAPIKeyApi) => ({ key }),
        deleteKey: (id: ProjectSecretAPIKeyApi['id']) => ({ id }),
        rollKey: (id: ProjectSecretAPIKeyApi['id']) => ({ id }),
        setScopeRadioValue: (key: string, action: string) => ({ key, action }),
        resetScopes: true,
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
    }),

    reducers({
        editingKeyId: [
            null as ProjectSecretAPIKeyApi['id'] | null,
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
            [] as ProjectSecretAPIKeyApi[],
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
                        return values.keys.filter((key: ProjectSecretAPIKeyApi) => key.id !== id)
                    } catch (error: any) {
                        lemonToast.error('Failed to delete project API key')
                        throw error
                    }
                },
                rollKey: async ({ id }: { id: string }) => {
                    const origKey = values.keys.find((key: ProjectSecretAPIKeyApi) => key.id === id)
                    if (!origKey) {
                        return values.keys
                    }

                    try {
                        const rolledKey = await api.projectSecretApiKeys.roll(id)
                        actions.showRollKeySuccessDialog(rolledKey)

                        const storedKey = { ...rolledKey, value: '' }
                        return values.keys.map((key: ProjectSecretAPIKeyApi) => (key.id === id ? storedKey : key))
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
                        ...values.keys.filter((k: ProjectSecretAPIKeyApi) => k.id !== values.editingKeyId),
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
            (s) => [s.searchTerm, s.featureFlags],
            (searchTerm: string, featureFlags): { key: string; label: string; disabledActions: APIScopeAction[] }[] => {
                const allActions: APIScopeAction[] = ['read', 'write']
                // llm_gateway:read is added only when the ai-gateway flag is on, mirroring the backend.
                const allowedScopeActions: string[] = [...PROJECT_SECRET_API_KEY_ALLOWED_API_SCOPE_ACTION]
                if (featureFlags[FEATURE_FLAGS.AI_GATEWAY]) {
                    allowedScopeActions.push('llm_gateway:read')
                }
                const allowedByKey = new Map<string, Set<APIScopeAction>>()
                for (const scopeAction of allowedScopeActions) {
                    const [key, action] = scopeAction.split(':') as [string, APIScopeAction]
                    if (!allowedByKey.has(key)) {
                        allowedByKey.set(key, new Set())
                    }
                    allowedByKey.get(key)!.add(action)
                }
                const scopes = Array.from(allowedByKey.entries()).map(([key, allowed]) => ({
                    key,
                    label: PROJECT_SECRET_SCOPE_OBJECT_NAMES[key] ?? capitalizeFirstLetter(key.replace(/_/g, ' ')),
                    disabledActions: allActions.filter((a) => !allowed.has(a)),
                }))
                if (!searchTerm.trim()) {
                    return scopes
                }
                const lowerSearch = searchTerm.toLowerCase()
                return scopes.filter(({ label }) => label.toLowerCase().includes(lowerSearch))
            },
        ],
        availablePresets: [
            (s) => [s.featureFlags],
            (featureFlags): ProjectSecretAPIKeyScopePreset[] =>
                PROJECT_SECRET_API_KEY_SCOPE_PRESETS.filter(
                    ({ value }) => value !== 'llm_gateway' || featureFlags[FEATURE_FLAGS.AI_GATEWAY]
                ),
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
                const key = values.keys.find((k: ProjectSecretAPIKeyApi) => k.id === id)
                actions.resetEditingKey({
                    label: key?.label ?? '',
                    scopes: (key?.scopes ?? []) as ProjectSecretAPIKeyAllowedScope[],
                    preset: undefined,
                })
            }
        },

        setScopeRadioValue: ({ key, action }: { key: string; action: string }) => {
            const newScopes = (values.editingKey.scopes || []).filter((s: string) => !s.startsWith(key + ':'))
            if (action !== 'none') {
                newScopes.push(`${key}:${action}` as ProjectSecretAPIKeyAllowedScope)
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
                title: 'Project secret API key ready',
                width: 536,
                content: (
                    <>
                        <p>Copy your new project secret API key:</p>
                        <CodeSnippet className="ph-no-capture" thing="project API key">
                            {key.value}
                        </CodeSnippet>
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
