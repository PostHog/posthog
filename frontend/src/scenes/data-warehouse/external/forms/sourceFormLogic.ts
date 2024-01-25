import { lemonToast } from '@posthog/lemon-ui'
import { actions, connect, kea, listeners, path, props } from 'kea'
import { forms } from 'kea-forms'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { urls } from 'scenes/urls'

import { ExternalDataSourceCreatePayload, ExternalDataSourceType } from '~/types'

import { getHubspotRedirectUri, sourceModalLogic } from '../sourceModalLogic'
import type { sourceFormLogicType } from './sourceFormLogicType'

export interface SourceFormProps {
    sourceType: ExternalDataSourceType
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
        actions: [
            sourceModalLogic,
            ['setDatabaseSchemas', 'onBack', 'onNext', 'selectConnector', 'toggleSourceModal', 'loadSources'],
        ],
    }),
    actions({
        onCancel: true,
        handleRedirect: (kind: string, searchParams: any) => ({ kind, searchParams }),
        onPostgresNext: true,
    }),
    listeners(({ actions }) => ({
        onCancel: () => {
            actions.resetExternalDataSource()
            actions.onBack()
            actions.selectConnector(null)
        },
        submitExternalDataSourceSuccess: () => {
            lemonToast.success('New Data Resource Created')
            actions.toggleSourceModal(false)
            actions.resetExternalDataSource()
            actions.loadSources()
            router.actions.push(urls.dataWarehouseSettings())
        },
        submitDatabaseSchemaFormSuccess: () => {
            actions.onNext()
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
        onPostgresNext: async () => {},
    })),
    urlToAction(({ actions }) => ({
        '/data-warehouse/:kind/redirect': ({ kind = '' }, searchParams) => {
            actions.handleRedirect(kind, searchParams)
        },
    })),
    forms(({ props, actions }) => ({
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
        databaseSchemaForm: {
            defaults: {
                prefix: '',
                payload: {
                    host: '',
                    port: '',
                    dbname: '',
                    user: '',
                    password: '',
                    schema: '',
                },
            },
            errors: ({ payload: { host, port, dbname, user, password, schema } }) => ({
                payload: {
                    host: !host && 'Please enter a host.',
                    port: !port && 'Please enter a port.',
                    dbname: !dbname && 'Please enter a dbname.',
                    user: !user && 'Please enter a user.',
                    password: !password && 'Please enter a password.',
                    schema: !schema && 'Please enter a schema.',
                },
            }),
            submit: async ({ payload: { host, port, dbname, user, password, schema }, prefix }) => {
                const schemas = await api.externalDataSources.database_schema(
                    host,
                    port,
                    dbname,
                    user,
                    password,
                    schema
                )
                actions.setDatabaseSchemas(schemas)

                return {
                    payload: {
                        host,
                        port,
                        dbname,
                        user,
                        password,
                        schema,
                    },
                    prefix,
                }
            },
        },
    })),
])
