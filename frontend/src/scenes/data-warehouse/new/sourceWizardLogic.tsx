import { lemonToast, Link } from '@posthog/lemon-ui'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb, ExternalDataSourceCreatePayload, ExternalDataSourceSyncSchema, SourceConfig } from '~/types'

import { sourceFormLogic } from '../external/forms/sourceFormLogic'
import { dataWarehouseSettingsLogic } from '../settings/dataWarehouseSettingsLogic'
import { dataWarehouseTableLogic } from './dataWarehouseTableLogic'
import type { sourceWizardLogicType } from './sourceWizardLogicType'

export const getHubspotRedirectUri = (): string => `${window.location.origin}/data-warehouse/hubspot/redirect`

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
    Zendesk: {
        name: 'Zendesk',
        caption: (
            <>
                Enter your Zendesk API key to automatically pull your Zendesk support data into the PostHog Data
                warehouse.
            </>
        ),
        fields: [
            {
                name: 'subdomain',
                label: 'Zendesk Subdomain',
                type: 'text',
                required: true,
                placeholder: '',
            },
            {
                name: 'api_key',
                label: 'API Key',
                type: 'text',
                required: true,
                placeholder: '',
            },
            {
                name: 'email_address',
                label: 'Zendesk Email Address',
                type: 'text',
                required: true,
                placeholder: '',
            },
        ],
    },
}

export const sourceWizardLogic = kea<sourceWizardLogicType>([
    path(['scenes', 'data-warehouse', 'external', 'sourceWizardLogic']),
    actions({
        selectConnector: (connector: SourceConfig | null) => ({ connector }),
        toggleManualLinkFormVisible: (visible: boolean) => ({ visible }),
        handleRedirect: (kind: string, searchParams: any) => ({ kind, searchParams }),
        onClear: true,
        onBack: true,
        onNext: true,
        onSubmit: true,
        setDatabaseSchemas: (schemas: ExternalDataSourceSyncSchema[]) => ({ schemas }),
        selectSchema: (schema: ExternalDataSourceSyncSchema) => ({ schema }),
        clearSource: true,
        updateSource: (source: Partial<ExternalDataSourceCreatePayload>) => ({ source }),
        createSource: true,
        setIsLoading: (isLoading: boolean) => ({ isLoading }),
        setSourceId: (id: string) => ({ sourceId: id }),
        closeWizard: true,
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
        actions: [dataWarehouseTableLogic, ['resetTable'], dataWarehouseSettingsLogic, ['loadSources']],
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
            [] as ExternalDataSourceSyncSchema[],
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
        source: [
            { payload: {}, prefix: '' } as {
                prefix: string
                payload: Record<string, any>
            },
            {
                updateSource: (state, { source }) => {
                    return {
                        prefix: source.prefix ?? state.prefix,
                        payload: {
                            ...(state.payload ?? {}),
                            ...(source.payload ?? {}),
                        },
                    }
                },
                clearSource: () => ({ payload: {}, prefix: '' }),
            },
        ],
        isLoading: [
            false as boolean,
            {
                onNext: () => false,
                setIsLoading: (_, { isLoading }) => isLoading,
            },
        ],
        sourceId: [
            null as string | null,
            {
                setSourceId: (_, { sourceId }) => sourceId,
            },
        ],
    }),
    selectors({
        canGoBack: [
            (s) => [s.currentStep],
            (currentStep): boolean => {
                return currentStep !== 4
            },
        ],
        canGoNext: [
            (s) => [s.currentStep, s.dataWarehouseSources, s.sourceId],
            (currentStep, allSources, sourceId): boolean => {
                const source = allSources?.results.find((n) => n.id === sourceId)

                if (currentStep === 4) {
                    return source !== undefined && source.status === 'Completed'
                }

                return true
            },
        ],
        showSkipButton: [
            (s) => [s.currentStep],
            (currentStep): boolean => {
                return currentStep === 4
            },
        ],
        nextButtonText: [
            (s) => [s.currentStep],
            (currentStep): string => {
                if (currentStep === 3) {
                    return 'Import'
                }

                if (currentStep === 4) {
                    return 'Finish'
                }

                return 'Next'
            },
        ],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.DataWarehouse,
                    name: 'Data Warehouse',
                    path: urls.dataWarehouse(),
                },
                { key: [Scene.DataWarehouse, 'New'], name: 'New' },
            ],
        ],
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

                if (currentStep === 4) {
                    return 'Importing your data...'
                }

                return ''
            },
        ],
        modalCaption: [
            (s) => [s.selectedConnector, s.currentStep],
            (selectedConnector, currentStep) => {
                if (currentStep === 2 && selectedConnector) {
                    return SOURCE_DETAILS[selectedConnector.name]?.caption
                }

                if (currentStep === 4) {
                    return "Sit tight as we import your data! After it's done, we'll show you a few examples to help you make the most of using the data within PostHog."
                }

                return ''
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        onClear: () => {
            actions.selectConnector(null)
            actions.clearSource()
            actions.toggleManualLinkFormVisible(false)
            actions.resetTable()
            actions.setIsLoading(false)
        },
        onSubmit: () => {
            // Shared function that triggers different actions depending on the current step

            if (values.currentStep === 1) {
                return
            }

            if (values.currentStep === 2) {
                if (values.selectedConnector?.name) {
                    const logic = sourceFormLogic({ sourceConfig: values.selectedConnector })
                    logic.actions.submitSourceConnectionDetails()
                } else {
                    // Used for manual S3 file links
                    dataWarehouseTableLogic.actions.submitTable()
                }
            }

            if (values.currentStep === 3 && values.selectedConnector?.name) {
                actions.updateSource({
                    payload: {
                        schemas: values.databaseSchema
                            .filter((schema) => schema.should_sync)
                            .map((schema) => schema.table),
                    },
                })
                actions.setIsLoading(true)
                actions.createSource()
            }

            if (values.currentStep === 4) {
                actions.closeWizard()
            }
        },
        closeWizard: () => {
            actions.clearSource()
            actions.loadSources(null)
            router.actions.push(urls.dataWarehouseSettings())
        },
        createSource: async () => {
            if (values.selectedConnector === null) {
                // This should never happen
                return
            }
            try {
                const { id } = await api.externalDataSources.create({
                    ...values.source,
                    source_type: values.selectedConnector.name,
                })
                lemonToast.success('New Data Resource Created')
                actions.setSourceId(id)
                actions.onNext()
            } catch (e: any) {
                lemonToast.error(e.data?.message ?? e.message)
            } finally {
                actions.setIsLoading(false)
            }
        },
    })),
])
