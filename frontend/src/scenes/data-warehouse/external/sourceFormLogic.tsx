import { lemonToast } from '@posthog/lemon-ui'
import { actions, connect, kea, listeners, path, props } from 'kea'
import { forms } from 'kea-forms'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { ExternalDataSourceCreatePayload, ExternalDataSourceType } from '~/types'

import type { sourceFormLogicType } from './sourceFormLogicType'
import { getHubspotRedirectUri, sourceModalLogic } from './sourceModalLogic'

export interface SourceFormProps {
    sourceType: ExternalDataSourceType
}

export interface SourceConfig {
    name: ExternalDataSourceType
    caption: string | JSX.Element
    fields: FieldConfig[]
    disabledReason?: string | null
}
interface FieldConfig {
    name: string
    label: string
    type: string
    required: boolean
    placeholder: string
}

export const SOURCE_DETAILS: Record<string, SourceConfig> = {
    Stripe: {
        name: 'Stripe',
        caption: (
            <>
                Enter your Stripe credentials to automatically pull your Stripe data into the PostHog Data warehouse.
                <br />
                You can find your account ID{' '}
                <Link to="https://dashboard.stripe.com/settings/user" target="_blank">
                    in your Stripe dashboard
                </Link>
                , and create a secret key{' '}
                <Link to="https://dashboard.stripe.com/apikeys" target="_blank">
                    here
                </Link>
                .
            </>
        ),
        fields: [
            {
                name: 'account_id',
                label: 'Account ID',
                type: 'text',
                required: true,
                placeholder: 'acct_...',
            },
            {
                name: 'client_secret',
                label: 'Client Secret',
                type: 'text',
                required: true,
                placeholder: 'sk_live_...',
            },
        ],
    },
    Hubspot: {
        name: 'Hubspot',
        fields: [],
        caption: '',
    },
}

const getPayloadDefaults = (sourceType: string): Record<string, any> => {
    switch (sourceType) {
        case 'Stripe':
            return {
                account_id: '',
                client_secret: '',
            }
        default:
            return {}
    }
}

const getErrorsDefaults = (sourceType: string): ((args: Record<string, any>) => Record<string, any>) => {
    switch (sourceType) {
        case 'Stripe':
            return ({ payload }) => ({
                payload: {
                    account_id: !payload.account_id && 'Please enter an account id.',
                    client_secret: !payload.client_secret && 'Please enter a client secret.',
                },
            })
        default:
            return () => ({})
    }
}

export const sourceFormLogic = kea<sourceFormLogicType>([
    path(['scenes', 'data-warehouse', 'external', 'sourceFormLogic']),
    props({} as SourceFormProps),
    connect({
        actions: [sourceModalLogic, ['onClear', 'toggleSourceModal', 'loadSources']],
    }),
    actions({
        onBack: true,
        handleRedirect: (kind: string, searchParams: any) => ({ kind, searchParams }),
    }),
    listeners(({ actions }) => ({
        onBack: () => {
            actions.resetExternalDataSource()
            actions.onClear()
        },
        submitExternalDataSourceSuccess: () => {
            lemonToast.success('New Data Resource Created')
            actions.toggleSourceModal(false)
            actions.resetExternalDataSource()
            actions.loadSources()
            router.actions.push(urls.dataWarehouseSettings())
        },
        submitExternalDataSourceFailure: ({ error }) => {
            lemonToast.error(error?.message || 'Something went wrong')
        },
        handleRedirect: async ({ kind, searchParams }) => {
            switch (kind) {
                case 'hubspot': {
                    actions.setExternalDataSourceValue('payload', {
                        code: searchParams.code,
                        redirect_uri: getHubspotRedirectUri(),
                    })
                    actions.setExternalDataSourceValue('source_type', 'Hubspot')
                    return
                }
                default:
                    lemonToast.error(`Something went wrong.`)
            }
        },
    })),
    urlToAction(({ actions }) => ({
        '/data-warehouse/:kind/redirect': ({ kind = '' }, searchParams) => {
            actions.handleRedirect(kind, searchParams)
        },
    })),
    forms(({ props }) => ({
        externalDataSource: {
            defaults: {
                prefix: '',
                source_type: props.sourceType,
                payload: getPayloadDefaults(props.sourceType),
            } as ExternalDataSourceCreatePayload,
            errors: getErrorsDefaults(props.sourceType),
            submit: async (payload: ExternalDataSourceCreatePayload) => {
                const newResource = await api.externalDataSources.create(payload)
                return newResource
            },
        },
    })),
])
