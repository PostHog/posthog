import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import api from 'lib/api'

import type { cliAuthorizeLogicType } from './cliAuthorizeLogicType'

export interface CLIAuthorizeForm {
    userCode: string
    projectId: number | null
}

export const cliAuthorizeLogic = kea<cliAuthorizeLogicType>([
    path(['scenes', 'authentication', 'cliAuthorizeLogic']),
    actions({
        setSuccess: (success: boolean) => ({ success }),
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
            } as CLIAuthorizeForm,
            errors: ({ userCode, projectId }) => ({
                userCode: !userCode
                    ? 'Please enter the code from your terminal'
                    : userCode.length !== 9
                      ? 'Code must be 9 characters (XXXX-XXXX)'
                      : undefined,
                projectId: !projectId ? 'Please select a project' : undefined,
            }),
            submit: async ({ userCode, projectId }) => {
                try {
                    const response = await api.create('api/cli-auth/authorize/', {
                        user_code: userCode.toUpperCase().replace(/\s/g, ''),
                        project_id: projectId,
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
    listeners(({ actions }) => ({
        submitAuthorizeSuccess: () => {
            actions.setSuccess(true)
        },
        submitAuthorizeFailure: () => {
            // Error handling is done in the form errors
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
