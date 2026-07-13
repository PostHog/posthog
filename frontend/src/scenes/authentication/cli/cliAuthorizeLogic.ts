import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import api from 'lib/api'
import { AGENT_CLI_API_KEY_SCOPES, API_SCOPES, APIScope, scopesArrayToObject } from 'lib/scopes'
import { userLogic } from 'scenes/userLogic'

import { OrganizationBasicType } from '~/types'

import type { cliAuthorizeLogicType } from './cliAuthorizeLogicType'

export type CLIUseCase = 'schema' | 'error_tracking' | 'endpoints' | 'agent-cli'

export interface CLIAuthorizeForm {
    userCode: string
    organizationId: string | null
    projectId: number | null
    scopes: string[]
}

// The agent set mirrors what the MCP requests, minus the actions disabled for
// manually-created keys. KNOWN LIMITATION: the few MCP tools needing those
// writes (desktop file-system writes, integration deletes, reminder + user-settings
// writes) therefore don't work through `posthog-cli api`.
const AGENT_SCOPES = AGENT_CLI_API_KEY_SCOPES

// Map use cases to their required scopes. The `agent-cli` set is generated from the
// MCP tool definitions (see agentScopes.generated.ts) so it stays in sync with
// what `posthog-cli api` / the MCP actually requires.
const USE_CASE_SCOPES: Record<CLIUseCase, string[]> = {
    schema: ['event_definition:read', 'property_definition:read'],
    error_tracking: ['error_tracking:write'],
    endpoints: ['endpoint:write', 'insight_variable:write'],
    'agent-cli': AGENT_SCOPES,
}

// Default use cases when none are specified. The CLI's agent interface drives
// this page, so a bare visit grants the full agent scope set.
const DEFAULT_USE_CASES: CLIUseCase[] = ['agent-cli']

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

// `read` for every scope that supports it (write-disabled scopes like file_system
// still allow read; only skip scopes whose read action is disabled or that are
// unprivileged-excluded, like llm_gateway, which the backend rejects for this flow).
const READ_ONLY_SCOPES = API_SCOPES.filter(
    ({ disabledActions, unprivilegedExcluded }) => !disabledActions?.includes('read') && !unprivilegedExcluded
).map(({ key }) => `${key}:read`)

// Presets offered in the consent screen dropdown. Values match the URL `use_cases`
// so a requested use case maps onto the matching preset.
export const CLI_SCOPE_PRESETS: { value: string; label: string; scopes: string[] }[] = [
    { value: 'agent-cli', label: 'Agent CLI', scopes: USE_CASE_SCOPES['agent-cli'] },
    { value: 'schema', label: 'Schema management', scopes: USE_CASE_SCOPES.schema },
    { value: 'error_tracking', label: 'Error tracking', scopes: USE_CASE_SCOPES.error_tracking },
    { value: 'endpoints', label: 'Endpoint execution', scopes: USE_CASE_SCOPES.endpoints },
    { value: 'read_only', label: 'Read-only access', scopes: READ_ONLY_SCOPES },
]

function sameScopeSet(a: string[], b: string[]): boolean {
    if (a.length !== b.length) {
        return false
    }
    const setB = new Set(b)
    return a.every((scope) => setB.has(scope))
}

// The dropdown shows the preset whose scope set exactly matches the current
// selection, or null ("Custom selection") once the user fine-tunes a row.
function presetForScopes(scopes: string[]): string | null {
    return CLI_SCOPE_PRESETS.find((preset) => sameScopeSet(preset.scopes, scopes))?.value ?? null
}

function parseCLIUseCase(useCase: string): CLIUseCase | null {
    if (useCase === 'agent') {
        return 'agent-cli'
    }
    if (useCase === 'schema' || useCase === 'error_tracking' || useCase === 'endpoints' || useCase === 'agent-cli') {
        return useCase
    }
    return null
}

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
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setScopePreset: (preset: string | null) => ({ preset }),
        resetScopes: true,
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
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
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
    forms(({ actions }) => ({
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
                    const errorCode = error?.data?.error || error?.code
                    if (errorCode === 'invalid_code') {
                        actions.setAuthorizeManualErrors({ userCode: 'Invalid or expired code. Please try again.' })
                    } else if (errorCode === 'expired') {
                        actions.setAuthorizeManualErrors({
                            userCode: 'This code has expired. Please request a new code in your terminal.',
                        })
                    } else if (errorCode === 'access_denied') {
                        actions.setAuthorizeManualErrors({ projectId: 'You do not have access to this project.' })
                    } else if (errorCode === 'invalid_project') {
                        actions.setAuthorizeManualErrors({ projectId: 'Project not found.' })
                    } else if (errorCode === 'invalid_scope') {
                        actions.setAuthorizeManualErrors({
                            scopes: 'One or more selected scopes are not permitted. Try choosing a different preset.',
                        })
                    } else {
                        actions.setAuthorizeManualErrors({ userCode: 'An error occurred. Please try again.' })
                    }
                    throw error
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
        filteredScopes: [
            (s) => [s.searchTerm],
            (searchTerm): APIScope[] => {
                const search = searchTerm.trim().toLowerCase()
                if (!search) {
                    return API_SCOPES
                }
                return API_SCOPES.filter(
                    (scope) =>
                        scope.key.toLowerCase().includes(search) || scope.objectPlural.toLowerCase().includes(search)
                )
            },
        ],
        allAccessSelected: [(s) => [s.authorize], (authorize): boolean => !!authorize?.scopes?.includes('*')],
        scopePreset: [(s) => [s.authorize], (authorize): string | null => presetForScopes(authorize?.scopes ?? [])],
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
                // Only show warning if the agent-cli use case was requested
                if (!requestedUseCases.includes('agent-cli')) {
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
        },
        setScopePreset: ({ preset }) => {
            const found = CLI_SCOPE_PRESETS.find((p) => p.value === preset)
            actions.setAuthorizeValue('scopes', found ? [...found.scopes] : [])
        },
        resetScopes: () => {
            actions.setAuthorizeValue('scopes', [])
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
            actions.setAuthorizeValue('scopes', getDefaultScopesForUseCases(useCases))
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
                const useCases = useCasesParam.split(',').flatMap((uc: string) => {
                    const parsedUseCase = parseCLIUseCase(uc)
                    return parsedUseCase ? [parsedUseCase] : []
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
