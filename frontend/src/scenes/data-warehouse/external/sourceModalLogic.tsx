import { Link } from '@posthog/lemon-ui'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { ExternalDataPostgresSchema, ExternalDataSourceType } from '~/types'

import { dataWarehouseTableLogic } from '../new_table/dataWarehouseTableLogic'
import { dataWarehouseSettingsLogic } from '../settings/dataWarehouseSettingsLogic'
import { dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'
import { sourceFormLogic } from './forms/sourceFormLogic'
import type { sourceModalLogicType } from './sourceModalLogicType'

export const getHubspotRedirectUri = (): string => `${window.location.origin}/data-warehouse/hubspot/redirect`

export interface SourceConfig {
    name: ExternalDataSourceType
    caption: string | React.ReactNode
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
    Postgres: {
        name: 'Postgres',
        caption: (
            <>
                Enter your Postgres credentials to automatically pull your Postgres data into the PostHog Data
                warehouse.
            </>
        ),
        fields: [
            {
                name: 'host',
                label: 'Host',
                type: 'text',
                required: true,
                placeholder: 'localhost',
            },
            {
                name: 'port',
                label: 'Port',
                type: 'number',
                required: true,
                placeholder: '5432',
            },
            {
                name: 'dbname',
                label: 'Database',
                type: 'text',
                required: true,
                placeholder: 'postgres',
            },
            {
                name: 'user',
                label: 'User',
                type: 'text',
                required: true,
                placeholder: 'postgres',
            },
            {
                name: 'password',
                label: 'Password',
                type: 'password',
                required: true,
                placeholder: 'password',
            },
            {
                name: 'schema',
                label: 'Schema',
                type: 'text',
                required: true,
                placeholder: 'public',
            },
        ],
    },
}

export const sourceModalLogic = kea<sourceModalLogicType>([
    path(['scenes', 'data-warehouse', 'external', 'sourceModalLogic']),
    actions({
        selectConnector: (connector: SourceConfig | null) => ({ connector }),
        toggleManualLinkFormVisible: (visible: boolean) => ({ visible }),
        handleRedirect: (kind: string, searchParams: any) => ({ kind, searchParams }),
        onClear: true,
        onBack: true,
        onNext: true,
        onSubmit: true,
        setDatabaseSchemas: (schemas: ExternalDataPostgresSchema[]) => ({ schemas }),
        selectSchema: (schema: ExternalDataPostgresSchema) => ({ schema }),
    }),
    connect({
        values: [
            dataWarehouseTableLogic,
            ['tableLoading'],
            dataWarehouseSettingsLogic,
            ['dataWarehouseSources'],
            preflightLogic,
            ['preflight'],
        ],
        actions: [
            dataWarehouseSceneLogic,
            ['toggleSourceModal'],
            dataWarehouseTableLogic,
            ['resetTable'],
            dataWarehouseSettingsLogic,
            ['loadSources'],
        ],
    }),
    reducers({
        selectedConnector: [
            null as SourceConfig | null,
            {
                selectConnector: (_, { connector }) => connector,
            },
        ],
        isManualLinkFormVisible: [
            false,
            {
                toggleManualLinkFormVisible: (_, { visible }) => visible,
            },
        ],
        currentStep: [
            1,
            {
                onNext: (state) => state + 1,
                onBack: (state) => state - 1,
                onClear: () => 1,
            },
        ],
        databaseSchema: [
            [] as ExternalDataPostgresSchema[],
            {
                setDatabaseSchemas: (_, { schemas }) => schemas,
                selectSchema: (state, { schema }) => {
                    const newSchema = state.map((s) => ({
                        ...s,
                        should_sync: s.table === schema.table ? !s.should_sync : s.should_sync,
                    }))
                    return newSchema
                },
            },
        ],
    }),
    selectors({
        showFooter: [
            (s) => [s.selectedConnector, s.isManualLinkFormVisible],
            (selectedConnector, isManualLinkFormVisible) => selectedConnector || isManualLinkFormVisible,
        ],
        connectors: [
            (s) => [s.dataWarehouseSources],
            (sources): SourceConfig[] => {
                return Object.values(SOURCE_DETAILS).map((connector) => ({
                    ...connector,
                    disabledReason:
                        sources && sources.results.find((source) => source.source_type === connector.name)
                            ? 'Already linked'
                            : null,
                }))
            },
        ],
        addToHubspotButtonUrl: [
            (s) => [s.preflight],
            (preflight) => {
                return () => {
                    const clientId = preflight?.data_warehouse_integrations?.hubspot.client_id

                    if (!clientId) {
                        return null
                    }

                    const scopes = [
                        'crm.objects.contacts.read',
                        'crm.objects.companies.read',
                        'crm.objects.deals.read',
                        'tickets',
                        'crm.objects.quotes.read',
                        'sales-email-read',
                    ]

                    const params = new URLSearchParams()
                    params.set('client_id', clientId)
                    params.set('redirect_uri', getHubspotRedirectUri())
                    params.set('scope', scopes.join(' '))

                    return `https://app.hubspot.com/oauth/authorize?${params.toString()}`
                }
            },
        ],
        modalTitle: [
            (s) => [s.currentStep],
            (currentStep) => {
                if (currentStep === 1) {
                    return 'Select a data source to get started'
                }
                if (currentStep === 2) {
                    return 'Link your data source'
                }

                if (currentStep === 3) {
                    return 'Select tables to import'
                }

                return ''
            },
        ],
        modalCaption: [
            (s) => [s.selectedConnector, s.currentStep],
            (selectedConnector, currentStep) => {
                if (currentStep == 2 && selectedConnector) {
                    return SOURCE_DETAILS[selectedConnector.name]?.caption
                }

                return ''
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        onClear: () => {
            actions.selectConnector(null)
            actions.toggleManualLinkFormVisible(false)
            actions.resetTable()
        },
        onSubmit: () => {
            // Shared function that triggers different actions depending on the current step

            if (values.currentStep === 1) {
                return
            }

            if (values.currentStep === 2) {
                if (values.selectedConnector?.name === 'Postgres') {
                    sourceFormLogic({ sourceType: 'Postgres' }).actions.submitDatabaseSchemaForm()
                } else if (values.selectedConnector?.name) {
                    sourceFormLogic({ sourceType: values.selectedConnector?.name }).actions.submitExternalDataSource()
                } else {
                    dataWarehouseTableLogic.actions.submitTable()
                }
            }

            if (values.currentStep === 3) {
                const logic = sourceFormLogic({ sourceType: 'Postgres' })

                logic.actions.setExternalDataSourceValue('payload', {
                    ...logic.values.databaseSchemaForm.payload,
                    schemas: values.databaseSchema.filter((schema) => schema.should_sync).map((schema) => schema.table),
                })
                logic.actions.setExternalDataSourceValue('prefix', logic.values.databaseSchemaForm.prefix)
                logic.actions.submitExternalDataSource()
            }
        },
    })),
])
