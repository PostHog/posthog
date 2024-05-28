import { lemonToast, Link } from '@posthog/lemon-ui'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import {
    Breadcrumb,
    ExternalDataSourceCreatePayload,
    ExternalDataSourceSyncSchema,
    PipelineTab,
    SourceConfig,
    SourceFieldConfig,
} from '~/types'

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
                type: 'email',
                required: true,
                placeholder: '',
            },
        ],
    },
}

export type ManualLinkProvider = 'aws' | 'google-cloud' | 'cloudflare-r2'

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
        toggleSchemaShouldSync: (schema: ExternalDataSourceSyncSchema, shouldSync: boolean) => ({ schema, shouldSync }),
        clearSource: true,
        updateSource: (source: Partial<ExternalDataSourceCreatePayload>) => ({ source }),
        createSource: true,
        setIsLoading: (isLoading: boolean) => ({ isLoading }),
        setSourceId: (id: string) => ({ sourceId: id }),
        closeWizard: true,
        cancelWizard: true,
        setStep: (step: number) => ({ step }),
        getDatabaseSchemas: true,
        setManualLinkingProvider: (provider: ManualLinkProvider) => ({ provider }),
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
            dataWarehouseTableLogic,
            ['resetTable', 'createTableSuccess'],
            dataWarehouseSettingsLogic,
            ['loadSources'],
        ],
    }),
    reducers({
        manualLinkingProvider: [
            null as ManualLinkProvider | null,
            {
                setManualLinkingProvider: (_, { provider }) => provider,
            },
        ],
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
                setStep: (_, { step }) => step,
            },
        ],
        databaseSchema: [
            [] as ExternalDataSourceSyncSchema[],
            {
                setDatabaseSchemas: (_, { schemas }) => schemas,
                toggleSchemaShouldSync: (state, { schema, shouldSync }) => {
                    const newSchema = state.map((s) => ({
                        ...s,
                        should_sync: s.table === schema.table ? shouldSync : s.should_sync,
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
        isManualLinkingSelected: [(s) => [s.selectedConnector], (selectedConnector): boolean => !selectedConnector],
        canGoBack: [
            (s) => [s.currentStep],
            (currentStep): boolean => {
                return currentStep !== 4
            },
        ],
        canGoNext: [
            (s) => [s.currentStep, s.dataWarehouseSources, s.sourceId, s.isManualLinkingSelected],
            (currentStep, allSources, sourceId, isManualLinkingSelected): boolean => {
                if (isManualLinkingSelected && currentStep == 2) {
                    return false
                }

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
            (s) => [s.currentStep, s.isManualLinkingSelected],
            (currentStep, isManualLinkingSelected): string => {
                if (currentStep === 3 && isManualLinkingSelected) {
                    return 'Link'
                }

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
        onBack: () => {
            if (values.currentStep <= 1) {
                actions.selectConnector(null)
            }
        },
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

            if (values.currentStep === 2 && values.selectedConnector?.name) {
                actions.submitSourceConnectionDetails()
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
            } else if (values.currentStep === 3 && values.isManualLinkFormVisible) {
                dataWarehouseTableLogic.actions.submitTable()
            }

            if (values.currentStep === 4) {
                actions.closeWizard()
            }
        },
        createTableSuccess: () => {
            actions.onClear()
            actions.clearSource()
            actions.loadSources(null)
            actions.resetSourceConnectionDetails()
        },
        closeWizard: () => {
            actions.onClear()
            actions.clearSource()
            actions.loadSources(null)
            actions.resetSourceConnectionDetails()

            if (router.values.location.pathname.includes(urls.dataWarehouseTable())) {
                router.actions.push(urls.dataWarehouseSettings())
            } else if (router.values.location.pathname.includes(urls.pipelineNodeDataWarehouseNew())) {
                router.actions.push(urls.pipeline(PipelineTab.DataImport))
            }
        },
        cancelWizard: () => {
            actions.onClear()
            actions.setStep(1)
            actions.loadSources(null)
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
                actions.resetSourceConnectionDetails()
                actions.loadSources(null)
                actions.onNext()
            } catch (e: any) {
                lemonToast.error(e.data?.message ?? e.message)
            } finally {
                actions.setIsLoading(false)
            }
        },
        handleRedirect: async ({ kind, searchParams }) => {
            switch (kind) {
                case 'hubspot': {
                    actions.updateSource({
                        source_type: 'Hubspot',
                        payload: {
                            code: searchParams.code,
                            redirect_uri: getHubspotRedirectUri(),
                        },
                    })
                    return
                }
                default:
                    lemonToast.error(`Something went wrong.`)
            }
        },
        submitSourceConnectionDetailsSuccess: () => {
            actions.getDatabaseSchemas()
        },
        getDatabaseSchemas: async () => {
            if (!values.selectedConnector) {
                return
            }

            actions.setIsLoading(true)

            try {
                const schemas = await api.externalDataSources.database_schema(
                    values.selectedConnector.name,
                    values.source.payload ?? {}
                )
                actions.setDatabaseSchemas(schemas)
                actions.onNext()
            } catch (e: any) {
                lemonToast.error(e.data?.message ?? e.message)
            }

            actions.setIsLoading(false)
        },
        setManualLinkingProvider: () => {
            actions.onNext()
        },
    })),
    urlToAction(({ actions }) => ({
        '/data-warehouse/:kind/redirect': ({ kind = '' }, searchParams) => {
            if (kind === 'hubspot') {
                router.actions.push(urls.dataWarehouseTable(), { kind, code: searchParams.code })
            }
        },
        '/data-warehouse/new': (_, searchParams) => {
            if (searchParams.kind == 'hubspot' && searchParams.code) {
                actions.selectConnector(SOURCE_DETAILS['Hubspot'])
                actions.handleRedirect(searchParams.kind, {
                    code: searchParams.code,
                })
                actions.setStep(2)
            }
        },
    })),
    forms(({ actions, values }) => ({
        sourceConnectionDetails: {
            defaults: {
                prefix: '',
                payload: {},
            } as {
                prefix: string
                payload: Record<string, any>
            },
            errors: (sourceValues) => {
                return getErrorsForFields(values.selectedConnector?.fields ?? [], sourceValues)
            },
            submit: async (sourceValues) => {
                if (values.selectedConnector) {
                    const payload = {
                        ...sourceValues,
                        source_type: values.selectedConnector.name,
                    }
                    actions.setIsLoading(true)

                    try {
                        await api.externalDataSources.source_prefix(payload.source_type, payload.prefix)
                        actions.updateSource(payload)
                        actions.setIsLoading(false)
                    } catch (e: any) {
                        if (e?.data?.message) {
                            actions.setSourceConnectionDetailsManualErrors({ prefix: e.data.message })
                        }
                        actions.setIsLoading(false)

                        throw e
                    }
                }
            },
        },
    })),
])

const getErrorsForFields = (
    fields: SourceFieldConfig[],
    { prefix, payload }: { prefix: string; payload: Record<string, any> }
): Record<string, any> => {
    const errors: Record<string, any> = {
        payload: {},
    }

    // Prefix errors
    if (!/^[a-zA-Z0-9_-]*$/.test(prefix ?? '')) {
        errors['prefix'] = "Please enter a valid prefix (only letters, numbers, and '_' or '-')."
    }

    // Payload errors
    for (const field of fields) {
        const fieldValue = payload[field.name]
        if (field.required && !fieldValue) {
            errors['payload'][field.name] = `Please enter a ${field.label.toLowerCase()}`
        }
    }

    return errors
}
