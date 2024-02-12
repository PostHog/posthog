import { actions, kea, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import { urlToAction } from 'kea-router'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import type { confirmOrganizationLogicType } from './confirmOrganizationLogicType'

export interface ConfirmOrganizationFormValues {
    organization_name?: string
    first_name?: string
    role_at_organization?: string
}

export const confirmOrganizationLogic = kea<confirmOrganizationLogicType>([
    path(['scenes', 'organization', 'confirmOrganizationLogic']),

    actions({
        setEmail: (email: string) => ({
            email,
        }),
        setShowNewOrgWarning: (show: boolean) => ({ show }),
    }),

    reducers({
        showNewOrgWarning: [
            false,
            {
                setShowNewOrgWarning: (_, { show }) => show,
            },
        ],
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
            errors: ({ organization_name, first_name }) => ({
                first_name: !first_name ? 'Please enter your name' : undefined,
                organization_name: !organization_name ? 'Please enter your organization name' : undefined,
            }),

            submit: async (formValues) => {
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
        '/organization/confirm-creation': (_, { email, organization_name, first_name }) => {
            actions.setConfirmOrganizationValues({ organization_name, first_name })
            actions.setEmail(email)
        },
    })),
])
