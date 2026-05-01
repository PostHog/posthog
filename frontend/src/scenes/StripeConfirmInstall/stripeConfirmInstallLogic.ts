import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router, urlToAction } from 'kea-router'

import api, { ApiError } from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { IntegrationKind } from '~/types'

import type { stripeConfirmInstallLogicType } from './stripeConfirmInstallLogicType'

export interface StripeConfirmInstallParams {
    code: string | null
    stripe_user_id: string | null
    account_id: string | null
    user_id: string | null
}

const EMPTY_PARAMS: StripeConfirmInstallParams = {
    code: null,
    stripe_user_id: null,
    account_id: null,
    user_id: null,
}

export const stripeConfirmInstallLogic = kea<stripeConfirmInstallLogicType>([
    path(['scenes', 'StripeConfirmInstall', 'stripeConfirmInstallLogic']),
    connect(() => ({
        actions: [integrationsLogic, ['loadIntegrations']],
    })),

    actions({
        setParams: (params: StripeConfirmInstallParams) => ({ params }),
        confirmInstall: true,
        cancelInstall: true,
        setSubmitting: (submitting: boolean) => ({ submitting }),
    }),

    reducers({
        params: [
            EMPTY_PARAMS,
            {
                setParams: (_, { params }) => params,
            },
        ],
        isSubmitting: [
            false,
            {
                setSubmitting: (_, { submitting }) => submitting,
            },
        ],
    }),

    selectors({
        hasRequiredParams: [(s) => [s.params], (params): boolean => !!params.code && !!params.stripe_user_id],
    }),

    listeners(({ actions, values }) => ({
        confirmInstall: async () => {
            if (!values.hasRequiredParams || values.isSubmitting) {
                return
            }
            actions.setSubmitting(true)
            const { code, stripe_user_id, account_id, user_id } = values.params
            try {
                const integration = await api.integrations.create({
                    kind: 'stripe' as IntegrationKind,
                    config: { code, stripe_user_id, account_id, user_id },
                })
                actions.loadIntegrations()
                lemonToast.success('Stripe integration connected.')
                const redirectUrl = new URL(urls.settings('project-integrations'), window.location.origin)
                redirectUrl.searchParams.set('integration_id', String(integration.id))
                router.actions.replace(redirectUrl.pathname + redirectUrl.search)
            } catch (e) {
                const detail = e instanceof ApiError ? e.detail : null
                lemonToast.error(detail || 'Failed to connect Stripe. The install link may have expired.')
                actions.setSubmitting(false)
            }
        },
        cancelInstall: () => {
            lemonToast.info('Stripe install cancelled.')
            router.actions.replace(urls.settings('project-integrations'))
        },
    })),

    urlToAction(({ actions }) => ({
        [urls.stripeConfirmInstall()]: (_, searchParams) => {
            actions.setParams({
                code: searchParams.code ?? null,
                stripe_user_id: searchParams.stripe_user_id ?? null,
                account_id: searchParams.account_id ?? null,
                user_id: searchParams.user_id ?? null,
            })
        },
    })),
])
