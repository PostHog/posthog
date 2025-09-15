import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { LemonBanner, LemonDialog } from '@posthog/lemon-ui'

import api from 'lib/api'
import { CodeSnippet } from 'lib/components/CodeSnippet'
import { OrganizationMembershipLevel } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { hasMembershipLevelOrHigher, organizationAllowsPersonalApiKeysForMembers } from 'lib/utils/permissioning'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { API_KEY_SCOPE_PRESETS } from '~/lib/scopes'
import { OrganizationBasicType, PersonalAPIKeyType, TeamBasicType, UserType } from '~/types'

import type { personalAPIKeysLogicType } from './personalAPIKeysLogicType'

export type EditingKeyFormValues = Pick<
    PersonalAPIKeyType,
    'label' | 'scopes' | 'scoped_organizations' | 'scoped_teams'
> & {
    preset?: string
    access_type?: 'all' | 'organizations' | 'teams'
}

export const personalAPIKeysLogic = kea<personalAPIKeysLogicType>([
    path(['lib', 'components', 'PersonalAPIKeys', 'personalAPIKeysLogic']),
    connect(() => ({
        values: [userLogic, ['user']],
    })),
    actions({
        setEditingKeyId: (id: PersonalAPIKeyType['id'] | null) => ({ id }),
        loadKeys: true,
        createKeySuccess: (key: PersonalAPIKeyType) => ({ key }),
        showRollKeySuccessDialog: (key: PersonalAPIKeyType, prevMaskedValue?: string | null) => ({
            key,
            prevMaskedValue,
        }),
        updateKey: (data: Partial<Pick<PersonalAPIKeyType, 'label' | 'scopes'>>) => data,
        deleteKey: (id: PersonalAPIKeyType['id']) => ({ id }),
        rollKey: (id: PersonalAPIKeyType['id']) => ({ id }),
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
    loaders(({ values, actions }) => ({
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
                rollKey: async ({ id }) => {
                    const origKey = values.keys.find((filteredKey) => filteredKey.id == id)
                    if (!origKey) {
                        return values.keys
                    }

                    const rolledKey = await api.personalApiKeys.roll(id)
                    actions.showRollKeySuccessDialog(rolledKey, origKey.mask_value)

                    // avoid persisting the raw value in state
                    rolledKey.value = undefined
                    return values.keys.map((filteredKey) => (filteredKey.id == id ? rolledKey : filteredKey))
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

        canUsePersonalApiKeys: [
            (s) => [s.user],
            (user: UserType | null): boolean => {
                const currentOrg = user?.organization
                if (!currentOrg) {
                    return true
                }

                if (currentOrg.membership_level && currentOrg.membership_level >= OrganizationMembershipLevel.Admin) {
                    return true
                }

                return organizationAllowsPersonalApiKeysForMembers(currentOrg)
            },
        ],

        isPersonalApiKeyIdDisabled: [
            (s) => [s.allOrganizations, s.allTeams, s.keys, s.getRestrictedOrganizationsForKey],
            (
                    allOrganizations: OrganizationBasicType[],
                    allTeams: TeamBasicType[] | null,
                    keys: PersonalAPIKeyType[],
                    getRestrictedOrganizationsForKey: (keyId: PersonalAPIKeyType['id']) => OrganizationBasicType[]
                ) =>
                (keyId: PersonalAPIKeyType['id']): boolean => {
                    const key = keys.find((k) => k.id === keyId)
                    if (!key) {
                        return false
                    }

                    const restrictedOrgs = getRestrictedOrganizationsForKey(keyId)

                    // If key is scoped to specific organizations
                    if (key.scoped_organizations?.length) {
                        // Key is disabled if ALL scoped organizations are restricted
                        return restrictedOrgs.length === key.scoped_organizations.length
                    }

                    // If key is scoped to specific teams
                    if (key.scoped_teams?.length && allTeams) {
                        // Get unique organization IDs from scoped teams
                        const teamOrgIds = new Set<string>()
                        key.scoped_teams.forEach((teamId) => {
                            const team = allTeams.find((t) => t.id === teamId)
                            if (team?.organization) {
                                teamOrgIds.add(team.organization)
                            }
                        })

                        // Key is disabled if ALL team organizations are restricted
                        return restrictedOrgs.length === teamOrgIds.size
                    }

                    // If key has all access, it's disabled if ALL user's organizations are restricted
                    return restrictedOrgs.length === allOrganizations.length
                },
        ],

        getRestrictedOrganizationsForKey: [
            (s) => [s.allOrganizations, s.keys, s.getRestrictedTeamsForKey],
            (
                    allOrganizations: OrganizationBasicType[],
                    keys: PersonalAPIKeyType[],
                    getRestrictedTeamsForKey: (keyId: PersonalAPIKeyType['id']) => TeamBasicType[]
                ) =>
                (keyId: PersonalAPIKeyType['id']): OrganizationBasicType[] => {
                    let restrictedOrgs: OrganizationBasicType[] = []
                    const key = keys.find((k) => k.id === keyId)

                    if (!key) {
                        return []
                    }

                    // If key is scoped to specific organizations
                    if (key.scoped_organizations?.length) {
                        restrictedOrgs = (key.scoped_organizations || [])
                            .map((orgId) => {
                                const org = allOrganizations.find((o) => o.id === orgId)
                                if (
                                    org &&
                                    !hasMembershipLevelOrHigher(org, OrganizationMembershipLevel.Admin) &&
                                    !organizationAllowsPersonalApiKeysForMembers(org)
                                ) {
                                    return org
                                }
                            })
                            .filter((x) => x) as OrganizationBasicType[]

                        return restrictedOrgs
                    }

                    // If key is scoped to specific teams
                    if (key.scoped_teams?.length) {
                        const restrictedTeams = getRestrictedTeamsForKey(keyId)
                        const orgIds = new Set<string>()

                        restrictedTeams.forEach((team) => {
                            if (team.organization) {
                                orgIds.add(team.organization)
                            }
                        })

                        restrictedOrgs = Array.from(orgIds)
                            .map((orgId) => allOrganizations.find((o) => o.id === orgId))
                            .filter((org) => org) as OrganizationBasicType[]

                        return restrictedOrgs
                    }

                    // If key has all access, check all user's organizations
                    allOrganizations.forEach((org) => {
                        if (
                            !hasMembershipLevelOrHigher(org, OrganizationMembershipLevel.Admin) &&
                            !organizationAllowsPersonalApiKeysForMembers(org)
                        ) {
                            restrictedOrgs.push(org)
                        }
                    })

                    return restrictedOrgs
                },
        ],

        getRestrictedTeamsForKey: [
            (s) => [s.allOrganizations, s.allTeams, s.keys],
            (allOrganizations: OrganizationBasicType[], allTeams: TeamBasicType[] | null, keys: PersonalAPIKeyType[]) =>
                (keyId: PersonalAPIKeyType['id']): TeamBasicType[] => {
                    const key = keys.find((k) => k.id === keyId)

                    if (!key || !allTeams || !key.scoped_teams?.length) {
                        return []
                    }

                    return key.scoped_teams
                        .map((teamId) => {
                            const team = allTeams.find((t: TeamBasicType) => t.id === teamId)
                            if (team?.organization) {
                                const org = allOrganizations.find((o) => o.id === team.organization)
                                if (
                                    org &&
                                    !hasMembershipLevelOrHigher(org, OrganizationMembershipLevel.Admin) &&
                                    !organizationAllowsPersonalApiKeysForMembers(org)
                                ) {
                                    return team
                                }
                            }
                        })
                        .filter((team) => team) as TeamBasicType[]
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
        showRollKeySuccessDialog: async ({ key, prevMaskedValue }) => {
            const value = key.value

            if (!value) {
                return
            }

            LemonDialog.open({
                title: 'Personal API key rolled',
                width: 536,
                content: (
                    <>
                        <p className="mb-4">Your key "{key.label}" has been rolled:</p>

                        <CodeSnippet className="ph-no-capture" thing="personal API key">
                            {value}
                        </CodeSnippet>

                        <LemonBanner type="warning" className="mt-4">
                            Your previous key{prevMaskedValue ? ` "${prevMaskedValue}"` : ''} is no longer valid.
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
                        access_type: preset.access_type,
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
