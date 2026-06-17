import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import api from 'lib/api'
import { API_SCOPES, scopesArrayToObject } from 'lib/scopes'
import { userLogic } from 'scenes/userLogic'

import { OrganizationBasicType } from '~/types'

import { AGENT_USE_CASE_SCOPES } from './agentScopes.generated'
import type { cliAuthorizeLogicType } from './cliAuthorizeLogicType'

export type CLIUseCase = 'schema' | 'error_tracking' | 'endpoints' | 'agent'

export interface CLIAuthorizeForm {
    userCode: string
    organizationId: string | null
    projectId: number | null
    scopes: string[]
}

// Actions the manual key-creation UI withholds from Personal API Keys
// (e.g. file_system:write, integration:write, user:write) — see `disabledActions`
// in lib/scopes. These are security footguns on a long-lived key (e.g.
// file_system:write's delete cascades into the backing resource, bypassing the
// finer per-resource scopes), so the CLI must not grant them either.
const KEY_CREATION_DISABLED_SCOPES = new Set(
    API_SCOPES.flatMap(({ key, disabledActions }) => (disabledActions ?? []).map((action) => `${key}:${action}`))
)

// The agent set mirrors what the MCP requests (agentScopes.generated.ts), minus
// the actions disabled for manually-created keys above. KNOWN LIMITATION: the few
// MCP tools needing those writes (desktop file-system writes, integration deletes,
// reminder + user-settings writes) therefore don't work through `posthog-cli api`.
const AGENT_SCOPES = AGENT_USE_CASE_SCOPES.filter((scope) => !KEY_CREATION_DISABLED_SCOPES.has(scope))

// Map use cases to their required scopes. The `agent` set is generated from the
// MCP tool definitions (see agentScopes.generated.ts) so it stays in sync with
// what `posthog-cli api` / the MCP actually requires.
const USE_CASE_SCOPES: Record<CLIUseCase, string[]> = {
    schema: ['event_definition:read', 'property_definition:read'],
    error_tracking: ['error_tracking:write'],
    endpoints: ['endpoint:write', 'insight_variable:write'],
    agent: AGENT_SCOPES,
}

// Default use cases when none are specified. The CLI's agent interface drives
// this page, so a bare visit grants the full agent scope set.
const DEFAULT_USE_CASES: CLIUseCase[] = ['agent']

function getDefaultScopesForUseCases(useCases: CLIUseCase[]): string[] {
    const scopesSet = new Set<string>()
    for (const useCase of useCases) {
        const scopes = USE_CASE_SCOPES[useCase] || []
        scopes.forEach((scope) => scopesSet.add(scope))
    }
    return Array.from(scopesSet)
}

// Pre-compute default scopes
const DEFAULT_SCOPES = getDefaultScopesForUseCases(DEFAULT_USE_CASES)

export const cliAuthorizeLogic = kea<cliAuthorizeLogicType>([
    path(['scenes', 'authentication', 'cli', 'cliAuthorizeLogic']),
    connect(() => ({
        actions: [userLogic, ['loadUserSuccess']],
        values: [userLogic, ['user']],
    })),
    actions({
        setSuccess: (success: boolean) => ({ success }),
        setScopeRadioValue: (key: string, action: string) => ({ key, action }),
        setRequestedUseCases: (useCases: CLIUseCase[]) => ({ useCases }),
        updateDisplayedScopeSnapshot: true,
        setDisplayedScopeValues: (values: Record<string, string>) => ({ values }),
    }),
    reducers({
        isSuccess: [
            false,
            {
                setSuccess: (_, { success }) => success,
            },
        ],
        requestedUseCases: [
            DEFAULT_USE_CASES,
            {
                setRequestedUseCases: (_, { useCases }) => useCases,
            },
        ],
        displayedScopeValues: [
            {} as Record<string, string>,
            {
                setDisplayedScopeValues: (_, { values }) => values,
            },
        ],
    }),
    loaders(() => ({
        projects: [
            [] as { id: number; name: string }[],
            {
                loadProjects: async (organizationId: string) => {
                    const response = await api.get(`api/organizations/${organizationId}/projects/`)
                    return response.results || []
                },
            },
        ],
    })),
    forms(() => ({
        authorize: {
            defaults: {
                userCode: '',
                organizationId: null,
                projectId: null,
                scopes: DEFAULT_SCOPES,
            } as CLIAuthorizeForm,
            errors: ({ userCode, organizationId, projectId, scopes }) => ({
                userCode: !userCode
                    ? 'Please enter the code from your terminal'
                    : userCode.length !== 9
                      ? 'Code must be 9 characters (XXXX-XXXX)'
                      : undefined,
                organizationId: !organizationId ? 'Please select an organization' : undefined,
                projectId: !projectId ? 'Please select a project' : undefined,
                scopes: !scopes?.length ? ('Your personal API key needs at least one scope' as any) : undefined,
            }),
            submit: async ({ userCode, projectId, scopes }) => {
                try {
                    const response = await api.create('api/cli-auth/authorize/', {
                        user_code: userCode.toUpperCase().replace(/\s/g, ''),
                        project_id: projectId,
                        scopes: scopes,
                    })
                    return response
                } catch (error: any) {
                    const errorCode = error?.code || error?.error
                    if (errorCode === 'invalid_code') {
                        throw { userCode: 'Invalid or expired code. Please try again.' }
                    } else if (errorCode === 'expired') {
                        throw { userCode: 'This code has expired. Please request a new code in your terminal.' }
                    } else if (errorCode === 'access_denied') {
                        throw { projectId: 'You do not have access to this project.' }
                    } else if (errorCode === 'invalid_project') {
                        throw { projectId: 'Project not found.' }
                    } else {
                        throw { userCode: 'An error occurred. Please try again.' }
                    }
                }
            },
        },
    })),
    selectors(() => ({
        organizations: [(s) => [s.user], (user): OrganizationBasicType[] => user?.organizations ?? []],
        formScopeRadioValues: [
            (s) => [s.authorize],
            (authorize): Record<string, string> => {
                if (!authorize || !authorize.scopes) {
                    return {}
                }
                return scopesArrayToObject(authorize.scopes)
            },
        ],
        missingSchemaScopes: [
            (s) => [s.authorize, s.requestedUseCases],
            (authorize, requestedUseCases): boolean => {
                // Only show warning if schema use case was requested
                if (!requestedUseCases.includes('schema')) {
                    return false
                }
                if (!authorize || !authorize.scopes) {
                    return false
                }
                // Warn if missing BOTH event_definition (read or write) AND property_definition (read or write)
                // Note: write permissions include read, so having write is sufficient
                const hasEventDefinition =
                    authorize.scopes.includes('event_definition:read') ||
                    authorize.scopes.includes('event_definition:write')
                const hasPropertyDefinition =
                    authorize.scopes.includes('property_definition:read') ||
                    authorize.scopes.includes('property_definition:write')
                return !hasEventDefinition || !hasPropertyDefinition
            },
        ],
        missingErrorTrackingScopes: [
            (s) => [s.authorize, s.requestedUseCases],
            (authorize, requestedUseCases): boolean => {
                // Only show warning if error_tracking use case was requested
                if (!requestedUseCases.includes('error_tracking')) {
                    return false
                }
                if (!authorize || !authorize.scopes) {
                    return false
                }
                // Warn if missing error_tracking entirely (neither read nor write)
                // Note: write permissions include read, so having write is sufficient
                return (
                    !authorize.scopes.includes('error_tracking:read') &&
                    !authorize.scopes.includes('error_tracking:write')
                )
            },
        ],
        missingEndpointsScopes: [
            (s) => [s.authorize, s.requestedUseCases],
            (authorize, requestedUseCases): boolean => {
                // Only show warning if endpoints use case was requested
                if (!requestedUseCases.includes('endpoints')) {
                    return false
                }
                if (!authorize || !authorize.scopes) {
                    return false
                }
                // Warn if missing endpoint entirely (neither read nor write)
                // Note: write permissions include read, so having write is sufficient
                return !authorize.scopes.includes('endpoint:read') && !authorize.scopes.includes('endpoint:write')
            },
        ],
        missingAgentScopes: [
            (s) => [s.authorize, s.requestedUseCases],
            (authorize, requestedUseCases): boolean => {
                // Only show warning if the agent use case was requested
                if (!requestedUseCases.includes('agent')) {
                    return false
                }
                if (!authorize || !authorize.scopes) {
                    return false
                }
                // The agent CLI can't even bootstrap (--agent-help, project context,
                // data discovery) without these. Write includes read, so either suffices.
                const hasUser = authorize.scopes.includes('user:read') || authorize.scopes.includes('user:write')
                const hasProject =
                    authorize.scopes.includes('project:read') || authorize.scopes.includes('project:write')
                const hasQuery = authorize.scopes.includes('query:read') || authorize.scopes.includes('query:write')
                return !hasUser || !hasProject || !hasQuery
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        loadProjectsSuccess: () => {
            const projectExistsInSelectedOrg = values.projects.some(
                (project) => project.id === values.authorize.projectId
            )
            if (projectExistsInSelectedOrg) {
                return
            }

            actions.setAuthorizeValue('projectId', values.projects[0]?.id ?? null)
        },
        setAuthorizeValue: (payload) => {
            if (payload.name === 'organizationId') {
                if (!payload.value) {
                    actions.setAuthorizeValue('projectId', null)
                    return
                }
                actions.loadProjects(payload.value)
            }

            // Initialize displayed scope values when scopes are first set
            if (payload.name === 'scopes' && Object.keys(values.displayedScopeValues).length === 0) {
                // Directly compute scope values from the scopes array being set
                const scopesArray = payload.value as string[]
                const scopeValues = scopesArrayToObject(scopesArray)
                actions.setDisplayedScopeValues(scopeValues)
            }
        },
        updateDisplayedScopeSnapshot: () => {
            // Update displayed scope values with current form values
            actions.setDisplayedScopeValues(values.formScopeRadioValues)
        },
        submitAuthorizeSuccess: () => {
            actions.setSuccess(true)
        },
        submitAuthorizeFailure: () => {
            // Error handling is done in the form errors
        },
        loadUserSuccess: ({ user }) => {
            if (values.authorize.organizationId) {
                return
            }

            const organizationId = user?.organization?.id || user?.organizations?.[0]?.id
            if (organizationId) {
                actions.setAuthorizeValue('organizationId', organizationId)
            }
        },
        setRequestedUseCases: ({ useCases }) => {
            // Update scopes when requested use cases change
            const newScopes = getDefaultScopesForUseCases(useCases)
            actions.setAuthorizeValue('scopes', newScopes)
            // Directly compute and update displayed scope values
            const scopeValues = scopesArrayToObject(newScopes)
            actions.setDisplayedScopeValues(scopeValues)
        },
        setScopeRadioValue: ({ key, action }) => {
            if (!values.authorize || !values.authorize.scopes) {
                return
            }

            // Remove existing scope with this key
            const filteredScopes = values.authorize.scopes.filter((scope) => !scope.startsWith(`${key}:`))

            // Add new scope if not 'none'
            const newScopes = action === 'none' ? filteredScopes : [...filteredScopes, `${key}:${action}`]

            actions.setAuthorizeValue('scopes', newScopes)
        },
    })),
    urlToAction(({ actions }) => ({
        '/cli/authorize': (_, searchParams) => {
            const code = searchParams.code
            if (code) {
                // Set the form field value directly
                actions.setAuthorizeValue('userCode', code)
            }

            // Parse use_cases from URL (comma-separated)
            const useCasesParam = searchParams.use_cases
            if (useCasesParam) {
                const useCases = useCasesParam.split(',').filter((uc: string): uc is CLIUseCase => {
                    return uc === 'schema' || uc === 'error_tracking' || uc === 'endpoints' || uc === 'agent'
                })
                if (useCases.length > 0) {
                    actions.setRequestedUseCases(useCases)
                }
            }
        },
    })),
    afterMount(({ actions, values }) => {
        if (values.authorize.organizationId) {
            return
        }

        const currentOrganizationId = values.user?.organization?.id || values.user?.organizations?.[0]?.id
        if (currentOrganizationId) {
            actions.setAuthorizeValue('organizationId', currentOrganizationId)
        }
    }),
])
