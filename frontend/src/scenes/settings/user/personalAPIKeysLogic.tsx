import { LemonDialog } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { CodeSnippet } from 'lib/components/CodeSnippet'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { userLogic } from 'scenes/userLogic'

import { OrganizationBasicType, PersonalAPIKeyType, TeamBasicType } from '~/types'

import type { personalAPIKeysLogicType } from './personalAPIKeysLogicType'

export const API_KEY_SCOPE_PRESETS = [
    { value: 'local_evaluation', label: 'Local feature flag evaluation', scopes: ['feature_flag:read'] },
    { value: 'analytics', label: 'Performing analytics queries', scopes: ['query:read'] },
    {
        value: 'project_management',
        label: 'Project & user management',
        scopes: ['project:write', 'organization:read', 'organization_member:write'],
    },
    { value: 'all_access', label: 'All access', scopes: ['*'] },
]

export type APIScope = {
    key: string
    disabledActions?: ('read' | 'write')[]
    description?: string
    warnings?: { [key: string]: JSX.Element }
}

export const APIScopes: APIScope[] = [
    { key: 'action' },
    { key: 'activity_log' },
    { key: 'annotation' },
    { key: 'batch_export' },
    { key: 'cohort' },
    { key: 'dashboard' },
    { key: 'dashboard_template' },
    { key: 'early_access_feature' },
    { key: 'event_definition' },
    { key: 'experiment' },
    { key: 'export' },
    { key: 'feature_flag' },
    { key: 'group' },
    { key: 'insight' },
    { key: 'query', disabledActions: ['write'] },
    { key: 'notebook' },
    { key: 'organization' },
    {
        key: 'organization_member',
        warnings: {
            write: (
                <>
                    <b>Warning:</b> This scope can be used to add or remove users from your organization which
                    effectively allows it to give access to many other scopes via the added user.
                </>
            ),
        },
    },
    { key: 'person' },
    { key: 'plugin' },
    {
        key: 'project',
        warnings: {
            write: (
                <>
                    <b>Warning:</b> This scope can be used to create or modify projects within your organization,
                    including settings about how data is ingested.
                </>
            ),
        },
    },
    { key: 'property_definition' },
    { key: 'scheduled_change' },
    { key: 'session_recording' },
    { key: 'session_recording_playlist' },
    { key: 'sharing_configuration' },
    { key: 'subscription' },
    { key: 'survey' },
    { key: 'user' },
]

export const personalAPIKeysLogic = kea<personalAPIKeysLogicType>([
    path(['lib', 'components', 'PersonalAPIKeys', 'personalAPIKeysLogic']),
    connect({
        values: [userLogic, ['user']],
    }),
    actions({
        setEditingKeyId: (id: PersonalAPIKeyType['id'] | null) => ({ id }),
        loadKeys: true,
        createKeySuccess: (key: PersonalAPIKeyType) => ({ key }),
        updateKey: (data: Partial<Pick<PersonalAPIKeyType, 'label' | 'scopes'>>) => data,
        deleteKey: (id: PersonalAPIKeyType['id']) => ({ id }),
        setScopeRadioValue: (key: string, action: string) => ({ key, action }),
        resetScopes: true,
        loadAllTeams: true,
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
                    return values.keys.filter((filteredKey) => filteredKey.id != id)
                },
            },
        ],

        allTeams: [
            null as TeamBasicType[] | null,
            {
                loadAllTeams: async () => {
                    return await api.loadPaginatedResults('api/projects')
                },
            },
        ],
    })),
    forms(({ values, actions }) => ({
        editingKey: {
            defaults: { label: '', scopes: [], scoped_organizations: [], scoped_teams: [] } as Pick<
                PersonalAPIKeyType,
                'label' | 'scopes' | 'scoped_organizations' | 'scoped_teams'
            > & { preset?: string },
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

                if (values.editingKeyId === 'new') {
                    actions.createKeySuccess(key)
                }

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
        allAccessSelected: [
            (s) => [s.editingKey],
            (editingKey): boolean => {
                return editingKey.scopes.includes('*')
            },
        ],

        allOrganizations: [
            (s) => [s.user],
            (user): OrganizationBasicType[] => {
                return user?.organizations ?? []
            },
        ],

        teamsWithinSelectedOrganizations: [
            (s) => [s.allTeams, s.editingKey],
            (allTeams, editingKey): TeamBasicType[] => {
                if (!editingKey?.scoped_organizations?.length) {
                    return allTeams ?? []
                }
                return allTeams?.filter((team) => editingKey.scoped_organizations?.includes(team.organization)) ?? []
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

            // When the user changes the list of valid orgs, clear the teams
            if (key === 'scoped_organizations' && values.editingKey.scoped_teams) {
                actions.setEditingKeyValue('scoped_teams', undefined)
            }
        },

        setEditingKeyId: async ({ id }) => {
            if (id) {
                const key = values.keys.find((key) => key.id === id)
                const formValues = {
                    label: key?.label ?? '',
                    scopes: key?.scopes ?? [],
                    preset: key?.scopes.includes('*') ? 'all_access' : undefined,
                }

                actions.resetEditingKey(formValues)
            }
        },

        resetScopes: () => {
            actions.setEditingKeyValue('scopes', [])
        },

        setScopeRadioValue: ({ key, action }) => {
            const newScopes = values.editingKey.scopes.filter((scope) => !scope.startsWith(key))
            if (action !== 'none') {
                newScopes.push(`${key}:${action}`)
            }

            actions.setEditingKeyValue('scopes', newScopes)
        },

        createKeySuccess: async ({ key }) => {
            const value = key.value

            if (!value) {
                return
            }

            LemonDialog.open({
                title: 'Personal API Key Created',
                content: (
                    <>
                        <p>Your API key has been created and copied to your clipboard.</p>

                        <CodeSnippet thing="personal API key">{value}</CodeSnippet>

                        <p>
                            <b>WARNING:</b> For security reasons the key value <b>will only ever be shown once</b>.
                            <br />
                            Copy it to your destination right away.
                        </p>
                    </>
                ),
            })

            await copyToClipboard(value, 'personal API key value')
        },
        deleteKeySuccess: () => {
            lemonToast.success(`Personal API key deleted`)
        },
    })),

    afterMount(({ actions }) => {
        actions.loadAllTeams()
    }),
])
