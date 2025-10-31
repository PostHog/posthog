import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import api from 'lib/api'

import type { cliAuthorizeLogicType } from './cliAuthorizeLogicType'

export const DEFAULT_CLI_SCOPES = ['event_definition:read', 'property_definition:read', 'error_tracking:write']

export interface CLIAuthorizeForm {
    userCode: string
    projectId: number | null
    scopes: string[]
}

export const cliAuthorizeLogic = kea<cliAuthorizeLogicType>([
    path(['scenes', 'authentication', 'cliAuthorizeLogic']),
    actions({
        setSuccess: (success: boolean) => ({ success }),
        setScopeRadioValue: (key: string, action: string) => ({ key, action }),
    }),
    reducers({
        isSuccess: [
            false,
            {
                setSuccess: (_, { success }) => success,
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
                scopes: DEFAULT_CLI_SCOPES,
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
                const result: Record<string, string> = {}

                if (!authorize || !authorize.scopes) {
                    return result
                }

                authorize.scopes.forEach((scope) => {
                    const [key, action] = scope.split(':')
                    result[key] = action
                })

                return result
            },
        ],
        missingSchemaScopes: [
            (s) => [s.authorize],
            (authorize): boolean => {
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
            (s) => [s.authorize],
            (authorize): boolean => {
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
        submitAuthorizeSuccess: () => {
            actions.setSuccess(true)
        },
        submitAuthorizeFailure: () => {
            // Error handling is done in the form errors
        },
        setScopeRadioValue: ({ key, action }) => {
            if (!values.authorize || !values.authorize.scopes) {
                return
            }
            const newScopes = values.authorize.scopes.filter((scope) => !scope.startsWith(key))
            if (action !== 'none') {
                newScopes.push(`${key}:${action}`)
            }

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
        },
    })),
    afterMount(({ actions }) => {
        actions.loadProjects()
    }),
])
