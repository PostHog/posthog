import { LemonBanner, LemonDialog } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { CodeSnippet } from 'lib/components/CodeSnippet'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { OrganizationBasicType, PersonalAPIKeyType, TeamBasicType } from '~/types'

import type { personalAPIKeysLogicType } from './personalAPIKeysLogicType'

export const MAX_API_KEYS_PER_USER = 10 // Same as in posthog/api/personal_api_key.py

export const API_KEY_SCOPE_PRESETS = [
    { value: 'local_evaluation', label: 'Local feature flag evaluation', scopes: ['feature_flag:read'] },
    {
        value: 'zapier',
        label: 'Zapier integration',
        scopes: ['action:read', 'query:read', 'project:read', 'organization:read', 'user:read', 'webhook:write'],
    },
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
    info?: string | JSX.Element
    disabledActions?: ('read' | 'write')[]
    disabledWhenProjectScoped?: boolean
    description?: string
    warnings?: Partial<Record<'read' | 'write', string | JSX.Element>>
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
    { key: 'organization', disabledWhenProjectScoped: true },
    {
        key: 'organization_member',
        disabledWhenProjectScoped: true,
        warnings: {
            write: (
                <>
                    This scope can be used to invite users to your organization,
                    <br />
                    effectively <strong>allowing access to other scopes via the added user</strong>.
                </>
            ),
        },
    },
    { key: 'person' },
    { key: 'plugin' },
    {
        key: 'project',
        warnings: {
            write: 'This scope can be used to create or modify projects, including settings about how data is ingested.',
        },
    },
    { key: 'property_definition' },
    { key: 'session_recording' },
    { key: 'session_recording_playlist' },
    { key: 'sharing_configuration' },
    { key: 'subscription' },
    { key: 'survey' },
    {
        key: 'user',
        disabledActions: ['write'],
        warnings: {
            read: (
                <>
                    This scope allows you to retrieve your own user object.
                    <br />
                    Note that the user object <strong>lists all organizations and projects you're in</strong>.
                </>
            ),
        },
    },
    { key: 'webhook', info: 'Webhook configuration is currently only enabled for the Zapier integration.' },
]

export type EditingKeyFormValues = Pick<
    PersonalAPIKeyType,
    'label' | 'scopes' | 'scoped_organizations' | 'scoped_teams'
> & {
    preset?: string
    access_type?: 'all' | 'organizations' | 'teams'
}

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
            defaults: {
                label: '',
                scopes: [],
                scoped_organizations: [],
                scoped_teams: [],
                access_type: undefined,
            } as EditingKeyFormValues,
            errors: ({ label, access_type, scopes, scoped_organizations, scoped_teams }) => ({
                label: !label ? 'Your API key needs a label' : undefined,
                scopes: !scopes?.length ? ('Your API key needs at least one scope' as any) : undefined,
                access_type: !access_type ? ('Select access mode' as any) : undefined,
                scoped_organizations:
                    access_type === 'organizations' && !scoped_organizations?.length
                        ? ('Select at least one organization' as any)
                        : undefined,
                scoped_teams:
                    access_type === 'teams' && !scoped_teams?.length
                        ? ('Select at least one project' as any)
                        : undefined,
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
    })),
    listeners(({ actions, values }) => ({
        touchEditingKeyField: ({ key }) => {
            if (key === 'label') {
                if (values.editingKey.label.toLowerCase().includes('zapier') && !values.editingKey.preset) {
                    actions.setEditingKeyValue('preset', 'zapier')
                    actions.setEditingKeyValue('access_type', 'all')
                }
            }
        },
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
            if (key === 'access_type') {
                actions.setEditingKeyValue('scoped_teams', [])
                actions.setEditingKeyValue('scoped_organizations', [])
            }
        },

        setEditingKeyId: async ({ id }) => {
            if (id) {
                const key = values.keys.find((key) => key.id === id)
                const formValues: EditingKeyFormValues = {
                    label: key?.label ?? '',
                    scopes: key?.scopes ?? [],
                    preset: key?.scopes.includes('*') ? 'all_access' : undefined,
                    scoped_organizations: key?.scoped_organizations ?? [],
                    scoped_teams: key?.scoped_teams ?? [],
                    access_type: key?.scoped_organizations?.length
                        ? 'organizations'
                        : key?.scoped_teams?.length
                        ? 'teams'
                        : id !== 'new'
                        ? 'all'
                        : undefined,
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
                title: 'Personal API key ready',
                width: 536,
                content: (
                    <>
                        <p className="mb-4">You can now use key "{key.label}" for authentication:</p>

                        <CodeSnippet className="ph-no-capture" thing="personal API key">
                            {value}
                        </CodeSnippet>

                        <LemonBanner type="warning" className="mt-4">
                            For security reasons the value above <em>will never be shown again</em>.
                            <br />
                            Copy it to your destination right away.
                        </LemonBanner>
                    </>
                ),
            })
        },
        deleteKeySuccess: () => {
            lemonToast.success(`Personal API key deleted`)
        },
    })),
    urlToAction(({ actions }) => ({
        [urls.settings('user-api-keys')]: (_, searchParams) => {
            const presetKey = searchParams.preset
            if (presetKey) {
                const preset = API_KEY_SCOPE_PRESETS.find((preset) => preset.value === presetKey)
                if (preset) {
                    actions.setEditingKeyId('new')
                    actions.setEditingKeyValues({
                        preset: preset.value,
                        label: preset.label,
                        scopes: preset.scopes,
                    })
                }
            }
        },
    })),
    actionToUrl(() => ({
        setEditingKeyId: ({ id }) => {
            if (!id) {
                // When the modal is closed, remove the preset from the URL
                return [router.values.location.pathname, {}, router.values.location.hash]
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadAllTeams()
    }),
])
