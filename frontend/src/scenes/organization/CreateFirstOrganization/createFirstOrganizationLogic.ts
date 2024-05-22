import { actions, connect, kea, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import { urlToAction } from 'kea-router'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { userLogic } from 'scenes/userLogic'

import type { createFirstOrganizationLogicType } from './createFirstOrganizationLogicType'

export interface CreateFirstOrganizationFormValues {
    organization_name?: string
    first_name?: string
    role_at_organization?: string
}

export const createFirstOrganizationLogic = kea<createFirstOrganizationLogicType>([
    path(['scenes', 'organization', 'createFirstOrganizationLogic']),
    connect({
        values: [userLogic, ['user']],
    }),

    actions({
        setShowNewOrgWarning: (show: boolean) => ({ show }),
    }),

    reducers({
        showNewOrgWarning: [
            false,
            {
                setShowNewOrgWarning: (_, { show }) => show,
            },
        ],
    }),

    forms(({ values }) => ({
        confirmOrganization: {
            defaults: {} as CreateFirstOrganizationFormValues,
            errors: ({ organization_name, first_name }) => ({
                first_name: !values.user?.first_name && !first_name ? 'Please enter your name' : undefined,
                organization_name: !organization_name ? 'Please enter your organization name' : undefined,
            }),

            submit: async (formValues) => {
                // Update user info as well as creating the org

                try {
                    await Promise.all([
                        api.update('api/users/@me/', {
                            first_name: formValues.first_name,
                        }),
                        api.create('api/organizations/', {
                            name: formValues.organization_name,
                        }),
                    ])
                } catch (error: any) {
                    lemonToast.error(error.detail || 'Failed to create organization')
                }

                window.location.reload()
            },
        },
    })),

    urlToAction(({ actions }) => ({
        '/organization/confirm-creation': (_, { organization_name, first_name }) => {
            actions.setConfirmOrganizationValues({ organization_name, first_name })
        },
    })),
])
