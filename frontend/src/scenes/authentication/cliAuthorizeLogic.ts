import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import api from 'lib/api'

import type { cliAuthorizeLogicType } from './cliAuthorizeLogicType'

export type CLIUseCase = 'schema' | 'error_tracking'

export interface CLIAuthorizeForm {
    userCode: string
    projectId: number | null
    scopes: string[]
}

// Utility functions for scope conversion
const scopesArrayToObject = (scopes: string[]): Record<string, string> => {
    const result: Record<string, string> = {}
    scopes.forEach((scope) => {
        const [key, action] = scope.split(':')
        if (key && action) {
            result[key] = action
        }
    })
    return result
}

const scopesObjectToArray = (scopesObj: Record<string, string>): string[] => {
    return Object.entries(scopesObj).map(([key, action]) => `${key}:${action}`)
}

// Map use cases to their required scopes
const USE_CASE_SCOPES: Record<CLIUseCase, string[]> = {
    schema: ['event_definition:read', 'property_definition:read'],
    error_tracking: ['error_tracking:write'],
}

// Default use cases when none are specified
const DEFAULT_USE_CASES: CLIUseCase[] = ['schema', 'error_tracking']

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
    path(['scenes', 'authentication', 'cliAuthorizeLogic']),
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
                loadProjects: async () => {
                    const response = await api.get('api/projects/')
                    return response.results || []
                },
            },
        ],
    })),
    forms(() => ({
        authorize: {
            defaults: {
                userCode: '',
                projectId: null,
                scopes: DEFAULT_SCOPES,
            } as CLIAuthorizeForm,
            errors: ({ userCode, projectId, scopes }) => ({
                userCode: !userCode
                    ? 'Please enter the code from your terminal'
                    : userCode.length !== 9
                      ? 'Code must be 9 characters (XXXX-XXXX)'
                      : undefined,
                projectId: !projectId ? 'Please select a project' : undefined,
                scopes: !scopes?.length ? ('Your API key needs at least one scope' as any) : undefined,
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
    })),
    listeners(({ actions, values }) => ({
        loadProjectsSuccess: () => {
            // Set default project to first project if not already set
            if (values.projects.length > 0 && !values.authorize.projectId) {
                actions.setAuthorizeValue('projectId', values.projects[0].id)
            }
        },
        setAuthorizeValue: (payload) => {
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

            // Convert current scopes array to object for easier manipulation
            const scopesObject = scopesArrayToObject(values.authorize.scopes)

            // Update the specific scope
            if (action === 'none') {
                delete scopesObject[key]
            } else {
                scopesObject[key] = action
            }

            // Convert back to array format
            const newScopes = scopesObjectToArray(scopesObject)

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
                    return uc === 'schema' || uc === 'error_tracking'
                })
                if (useCases.length > 0) {
                    actions.setRequestedUseCases(useCases)
                }
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadProjects()
    }),
])
