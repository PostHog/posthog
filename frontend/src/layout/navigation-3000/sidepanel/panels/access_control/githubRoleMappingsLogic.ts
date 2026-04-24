import { actions, afterMount, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import {
    integrationsList,
    roleExternalReferencesCreate,
    roleExternalReferencesDestroy,
    roleExternalReferencesList,
} from 'products/integrations/frontend/generated/api'
import type {
    IntegrationConfigApi,
    RoleExternalReferenceApi,
} from 'products/integrations/frontend/generated/api.schemas'

export type GitHubTeamType = {
    id: number
    slug: string
    name: string
}

type GitHubTeamsResponse = {
    teams: GitHubTeamType[]
    has_more: boolean
}

function getIntegrationAccountType(integration: IntegrationConfigApi): string | null {
    if (!integration.config || typeof integration.config !== 'object') {
        return null
    }

    const account = (integration.config as Record<string, unknown>).account
    if (!account || typeof account !== 'object') {
        return null
    }

    const accountType = (account as Record<string, unknown>).type
    return typeof accountType === 'string' ? accountType : null
}

export function getIntegrationAccountName(integration: IntegrationConfigApi): string | null {
    if (!integration.config || typeof integration.config !== 'object') {
        return null
    }

    const account = (integration.config as Record<string, unknown>).account
    if (!account || typeof account !== 'object') {
        return null
    }

    const accountName = (account as Record<string, unknown>).name
    return typeof accountName === 'string' ? accountName : null
}

export const githubRoleMappingsLogic = kea([
    path(['scenes', 'accessControl', 'githubRoleMappingsLogic']),
    props({} as { roleId: string }),
    connect(() => ({
        values: [teamLogic, ['currentProjectId'], organizationLogic, ['currentOrganization']],
    })),
    actions({
        openExternalReferenceModal: true,
        closeExternalReferenceModal: true,
        setSelectedGithubIntegrationId: (integrationId: number | null) => ({ integrationId }),
        setSelectedGithubTeamId: (teamId: number | null) => ({ teamId }),
        attachSelectedGithubTeam: true,
        createGitHubRoleExternalReference: (payload: {
            roleId: string
            providerOrganizationId: string
            team: GitHubTeamType
        }) => ({ payload }),
        deleteRoleExternalReference: (referenceId: string) => ({ referenceId }),
    }),
    reducers({
        externalReferenceModalOpen: [
            false,
            {
                openExternalReferenceModal: () => true,
                closeExternalReferenceModal: () => false,
                createGitHubRoleExternalReferenceSuccess: () => false,
            },
        ],
        selectedGithubIntegrationId: [
            null as number | null,
            {
                setSelectedGithubIntegrationId: (_, { integrationId }) => integrationId,
            },
        ],
        selectedGithubTeamId: [
            null as number | null,
            {
                setSelectedGithubTeamId: (_, { teamId }) => teamId,
                closeExternalReferenceModal: () => null,
                createGitHubRoleExternalReferenceSuccess: () => null,
                setSelectedGithubIntegrationId: () => null,
            },
        ],
        githubTeamsError: [
            null as string | null,
            {
                loadGithubTeams: () => null,
                loadGithubTeamsSuccess: () => null,
                loadGithubTeamsFailure: (_, { errorObject }) => {
                    const detail = (errorObject as Record<string, unknown> | undefined)?.detail
                    return typeof detail === 'string' ? detail : 'Failed to load GitHub teams'
                },
            },
        ],
    }),
    loaders(({ values }) => ({
        roleExternalReferences: [
            [] as RoleExternalReferenceApi[],
            {
                loadRoleExternalReferences: async () => {
                    const organizationId = values.currentOrganization?.id
                    if (!organizationId) {
                        return []
                    }
                    const response = await roleExternalReferencesList(organizationId, {
                        provider: 'github',
                        limit: 1000,
                    })
                    return response.results
                },
                createGitHubRoleExternalReference: async ({ payload }) => {
                    const organizationId = values.currentOrganization?.id
                    if (!organizationId) {
                        throw new Error('Organization not found')
                    }
                    await roleExternalReferencesCreate(organizationId, {
                        provider: 'github',
                        provider_organization_id: payload.providerOrganizationId,
                        provider_role_id: String(payload.team.id),
                        provider_role_slug: payload.team.slug,
                        provider_role_name: payload.team.name.trim() || payload.team.slug,
                        role: payload.roleId,
                    })
                    const response = await roleExternalReferencesList(organizationId, {
                        provider: 'github',
                        limit: 1000,
                    })
                    return response.results
                },
                deleteRoleExternalReference: async ({ referenceId }) => {
                    const organizationId = values.currentOrganization?.id
                    if (!organizationId) {
                        throw new Error('Organization not found')
                    }
                    await roleExternalReferencesDestroy(organizationId, referenceId)
                    return values.roleExternalReferences.filter((reference) => reference.id !== referenceId)
                },
            },
        ],
        githubIntegrations: [
            [] as IntegrationConfigApi[],
            {
                loadGithubIntegrations: async () => {
                    const response = await integrationsList(String(values.currentProjectId), { limit: 200 })
                    return response.results.filter((integration) => integration.kind === 'github')
                },
            },
        ],
        githubTeams: [
            [] as GitHubTeamType[],
            {
                loadGithubTeams: async ({ integrationId, search }: { integrationId: number; search: string }) => {
                    const response = await api.get<GitHubTeamsResponse>(
                        `api/projects/${values.currentProjectId}/integrations/${integrationId}/github_teams/?search=${encodeURIComponent(search)}&limit=100&offset=0`
                    )
                    return response.teams
                        .filter(
                            (team): team is GitHubTeamType =>
                                typeof team.id === 'number' &&
                                typeof team.slug === 'string' &&
                                typeof team.name === 'string'
                        )
                        .map((team) => ({ id: team.id, slug: team.slug, name: team.name.trim() || team.slug }))
                },
            },
        ],
    })),
    selectors(({ props }) => ({
        organizationGithubIntegrations: [
            (s) => [s.githubIntegrations],
            (githubIntegrations: IntegrationConfigApi[]): IntegrationConfigApi[] =>
                githubIntegrations.filter(
                    (integration) => getIntegrationAccountType(integration)?.toLowerCase() === 'organization'
                ),
        ],
        githubReferencesForRole: [
            (s) => [s.roleExternalReferences],
            (roleExternalReferences: RoleExternalReferenceApi[]): RoleExternalReferenceApi[] =>
                roleExternalReferences.filter((reference) => reference.role === props.roleId),
        ],
        selectedGithubIntegration: [
            (s) => [s.organizationGithubIntegrations, s.selectedGithubIntegrationId],
            (integrations: IntegrationConfigApi[], integrationId: number | null): IntegrationConfigApi | null =>
                integrations.find((integration) => integration.id === integrationId) ?? null,
        ],
        selectedGithubIntegrationAccountName: [
            (s) => [s.selectedGithubIntegration],
            (integration: IntegrationConfigApi | null): string | null =>
                integration ? getIntegrationAccountName(integration) : null,
        ],
        availableGithubTeams: [
            (s) => [s.roleExternalReferences, s.githubTeams, s.selectedGithubIntegrationAccountName],
            (
                roleExternalReferences: RoleExternalReferenceApi[],
                githubTeams: GitHubTeamType[],
                selectedGithubIntegrationAccountName: string | null
            ): GitHubTeamType[] => {
                const mappedGithubTeamIds = new Set(
                    roleExternalReferences
                        .filter((reference) =>
                            selectedGithubIntegrationAccountName
                                ? reference.provider_organization_id === selectedGithubIntegrationAccountName
                                : true
                        )
                        .map((reference) => reference.provider_role_id)
                )
                return githubTeams.filter((team) => !mappedGithubTeamIds.has(String(team.id)))
            },
        ],
        selectedGithubTeam: [
            (s) => [s.availableGithubTeams, s.selectedGithubTeamId],
            (teams: GitHubTeamType[], selectedGithubTeamId: number | null): GitHubTeamType | null =>
                teams.find((team) => team.id === selectedGithubTeamId) ?? null,
        ],
        noTeamsHelpText: [
            (s) => [
                s.githubTeamsError,
                s.selectedGithubIntegration,
                s.selectedGithubIntegrationAccountName,
                s.githubTeams,
            ],
            (
                githubTeamsError: string | null,
                selectedGithubIntegration: IntegrationConfigApi | null,
                selectedGithubIntegrationAccountName: string | null,
                githubTeams: GitHubTeamType[]
            ): string => {
                if (githubTeamsError) {
                    return `Could not load teams for ${selectedGithubIntegrationAccountName || 'this integration'}: ${githubTeamsError}`
                }
                if (!selectedGithubIntegration) {
                    return 'Select a GitHub organization integration to load teams.'
                }
                if (githubTeams.length === 0) {
                    return `No teams were returned for ${selectedGithubIntegrationAccountName || 'this integration'}. The installation might not have team access.`
                }
                return 'All fetched teams are already mapped to a role.'
            },
        ],
        canAttachSelectedGithubTeam: [
            (s) => [s.selectedGithubIntegration, s.selectedGithubTeam],
            (
                selectedGithubIntegration: IntegrationConfigApi | null,
                selectedGithubTeam: GitHubTeamType | null
            ): boolean => !!selectedGithubIntegration && !!selectedGithubTeam,
        ],
    })),
    listeners(({ actions, values, props }) => ({
        openExternalReferenceModal: () => {
            if (values.selectedGithubIntegrationId) {
                actions.loadGithubTeams({ integrationId: values.selectedGithubIntegrationId, search: '' })
            }
        },
        setSelectedGithubIntegrationId: ({ integrationId }) => {
            if (integrationId) {
                actions.loadGithubTeams({ integrationId, search: '' })
            }
        },
        attachSelectedGithubTeam: () => {
            if (!values.selectedGithubIntegration || !values.selectedGithubTeam) {
                return
            }

            const providerOrganizationId = getIntegrationAccountName(values.selectedGithubIntegration)
            if (!providerOrganizationId) {
                return
            }

            actions.createGitHubRoleExternalReference({
                roleId: props.roleId,
                providerOrganizationId,
                team: values.selectedGithubTeam,
            })
        },
        loadGithubIntegrationsSuccess: ({ githubIntegrations }) => {
            const defaultIntegration = githubIntegrations.find(
                (integration) => getIntegrationAccountType(integration)?.toLowerCase() === 'organization'
            )
            actions.setSelectedGithubIntegrationId(defaultIntegration?.id ?? null)
        },
        loadGithubTeamsFailure: ({ errorObject }) => {
            const detail = (errorObject as Record<string, unknown> | undefined)?.detail
            lemonToast.error(
                typeof detail === 'string' ? `Load github teams failed: ${detail}` : 'Load github teams failed'
            )
        },
        createGitHubRoleExternalReferenceSuccess: () => {
            lemonToast.success('GitHub team attached to role')
            actions.closeExternalReferenceModal()
        },
        createGitHubRoleExternalReferenceFailure: ({ errorObject }) => {
            const detail = (errorObject as Record<string, unknown> | undefined)?.detail
            lemonToast.error(typeof detail === 'string' ? detail : 'Failed to attach GitHub team')
        },
        deleteRoleExternalReferenceSuccess: () => {
            lemonToast.success('External reference removed')
        },
        deleteRoleExternalReferenceFailure: () => {
            lemonToast.error('Failed to remove external reference')
        },
    })),
    afterMount(({ actions }) => {
        actions.loadRoleExternalReferences()
        actions.loadGithubIntegrations()
    }),
])
