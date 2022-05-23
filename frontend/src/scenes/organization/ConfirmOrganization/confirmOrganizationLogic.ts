import { actions, kea, path, reducers } from 'kea'

import api from 'lib/api'
import { urlToAction } from 'kea-router'

import type { confirmOrganizationLogicType } from './confirmOrganizationLogicType'
import { forms } from 'kea-forms'
import { lemonToast } from 'lib/components/lemonToast'

interface ConfirmOrganizationFormValues {
    organization_name?: string
    user_name?: string
}

export const confirmOrganizationLogic = kea<confirmOrganizationLogicType<ConfirmOrganizationFormValues>>([
    path(['scenes', 'organization', 'confirmOrganizationLogic']),

    actions({
        setEmail: (email: string) => ({
            email,
        }),
    }),

    reducers({
        email: [
            '',
            {
                setEmail: (_, { email }) => email,
            },
        ],
    }),

    forms(() => ({
        confirmOrganization: {
            defaults: {} as ConfirmOrganizationFormValues,
            errors: ({ organization_name, user_name }) => ({
                user_name: !user_name ? 'Please enter your name' : undefined,
                organization_name: !organization_name ? 'Please enter your organization name' : undefined,
            }),

            submit: async (formValues) => {
                console.log('submit2', formValues)
                try {
                    const response = await api.create('api/social_signup/', {
                        ...formValues,
                    })
                    location.href = response.success_url || '/'
                } catch (error: any) {
                    lemonToast.error(error.detail || 'Failed to create organization')
                }
            },
        },
    })),

    urlToAction(({ actions }) => ({
        '/organization/confirm-creation': (_, { email, organization_name, user_name }) => {
            console.log('confirm-creation', email, organization_name, user_name)
            actions.setConfirmOrganizationValues({ organization_name, user_name })
            actions.setEmail(email)
        },
    })),
])
