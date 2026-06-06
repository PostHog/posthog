import { actions, kea, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import { urlToAction } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { getRelativeNextPath } from 'lib/utils'

import type { confirmOrganizationLogicType } from './confirmOrganizationLogicType'

export interface ConfirmOrganizationFormValues {
    organization_name?: string
    first_name?: string
    role_at_organization?: string
    referral_source?: string
    referral_source_ai_prompt?: string
}

export const confirmOrganizationLogic = kea<confirmOrganizationLogicType>([
    path(['scenes', 'organization', 'confirmOrganizationLogic']),

    actions({
        setEmail: (email: string) => ({
            email,
        }),
        setNext: (next: string | null) => ({ next }),
    }),

    reducers({
        email: [
            '',
            {
                setEmail: (_, { email }) => email,
            },
        ],
        next: [
            null as string | null,
            {
                setNext: (_, { next }) => next,
            },
        ],
    }),

    forms(({ values }) => ({
        confirmOrganization: {
            defaults: {} as ConfirmOrganizationFormValues,
            errors: ({ organization_name, first_name }) => ({
                first_name: !first_name ? 'Please enter your name' : undefined,
                organization_name: !organization_name ? 'Please enter your organization name' : undefined,
            }),

            submit: async (formValues) => {
                await api
                    .create('api/social_signup/', {
                        ...formValues,
                    })
                    .then(() => {
                        // `next` is already sanitized to a same-origin relative path by getRelativeNextPath in urlToAction
                        // nosemgrep: javascript.browser.security.open-redirect.js-open-redirect
                        location.href = values.next || '/'
                    })
                    .catch((error: any) => {
                        console.error('error', error)
                        lemonToast.error(error.detail || 'Failed to create organization')
                    })
            },
        },
    })),

    urlToAction(({ actions }) => ({
        '/organization/confirm-creation': (_, { email, organization_name, first_name, next }) => {
            actions.setConfirmOrganizationValues({ organization_name, first_name })
            actions.setEmail(email)
            actions.setNext(getRelativeNextPath(next, location))
        },
    })),
])
