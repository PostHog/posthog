import { lemonToast, Link } from '@posthog/lemon-ui'
import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import posthog from 'posthog-js'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import {
    Breadcrumb,
    ExternalDataSourceCreatePayload,
    ExternalDataSourceSyncSchema,
    ExternalDataSourceType,
    manualLinkSources,
    ManualLinkSourceType,
    PipelineTab,
    SourceConfig,
    SourceFieldConfig,
} from '~/types'

import { dataWarehouseSettingsLogic } from '../settings/dataWarehouseSettingsLogic'
import { dataWarehouseTableLogic } from './dataWarehouseTableLogic'
import type { sourceWizardLogicType } from './sourceWizardLogicType'

const Caption = (): JSX.Element => (
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
)

export const getHubspotRedirectUri = (): string => `${window.location.origin}/data-warehouse/hubspot/redirect`

export const SOURCE_DETAILS: Record<ExternalDataSourceType, SourceConfig> = {
    Stripe: {
        name: 'Stripe',
        caption: <Caption />,
        fields: [
            {
                name: 'account_id',
                label: 'Account id',
                type: 'text',
                required: false,
                placeholder: 'acct_...',
            },
            {
                name: 'client_secret',
                label: 'Client secret',
                type: 'password',
                required: true,
                placeholder: 'sk_live_...',
            },
        ],
    },
    Hubspot: {
        name: 'Hubspot',
        fields: [],
        caption: 'Succesfully authenticated with Hubspot. Please continue here to complete the source setup',
        oauthPayload: ['code'],
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
                placeholder: '',
            },
            {
                name: 'schema',
                label: 'Schema',
                type: 'text',
                required: true,
                placeholder: 'public',
            },
            {
                name: 'ssh-tunnel',
                label: 'Use SSH tunnel?',
                type: 'switch-group',
                default: false,
                fields: [
                    {
                        name: 'host',
                        label: 'Tunnel host',
                        type: 'text',
                        required: true,
                        placeholder: 'localhost',
                    },
                    {
                        name: 'port',
                        label: 'Tunnel port',
                        type: 'number',
                        required: true,
                        placeholder: '22',
                    },
                    {
                        type: 'select',
                        name: 'auth_type',
                        label: 'Authentication type',
                        required: true,
                        defaultValue: 'password',
                        options: [
                            {
                                label: 'Password',
                                value: 'password',
                                fields: [
                                    {
                                        name: 'username',
                                        label: 'Tunnel username',
                                        type: 'text',
                                        required: true,
                                        placeholder: 'User1',
                                    },
                                    {
                                        name: 'password',
                                        label: 'Tunnel password',
                                        type: 'password',
                                        required: true,
                                        placeholder: '',
                                    },
                                ],
                            },
                            {
                                label: 'Key pair',
                                value: 'keypair',
                                fields: [
                                    {
                                        name: 'username',
                                        label: 'Tunnel username',
                                        type: 'text',
                                        required: false,
                                        placeholder: 'User1',
                                    },
                                    {
                                        name: 'private_key',
                                        label: 'Tunnel private key',
                                        type: 'textarea',
                                        required: true,
                                        placeholder: '',
                                    },
                                    {
                                        name: 'passphrase',
                                        label: 'Tunnel passphrase',
                                        type: 'password',
                                        required: false,
                                        placeholder: '',
                                    },
                                ],
                            },
                        ],
                    },
                ],
            },
        ],
    },
    MySQL: {
        name: 'MySQL',
        caption: (
            <>
                Enter your MySQL/MariaDB credentials to automatically pull your MySQL data into the PostHog Data
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
                placeholder: '3306',
            },
            {
                name: 'dbname',
                label: 'Database',
                type: 'text',
                required: true,
                placeholder: 'mysql',
            },
            {
                name: 'user',
                label: 'User',
                type: 'text',
                required: true,
                placeholder: 'mysql',
            },
            {
                name: 'password',
                label: 'Password',
                type: 'password',
                required: true,
                placeholder: '',
            },
            {
                name: 'schema',
                label: 'Schema',
                type: 'text',
                required: true,
                placeholder: 'public',
            },
            {
                name: 'ssh-tunnel',
                label: 'Use SSH tunnel?',
                type: 'switch-group',
                default: false,
                fields: [
                    {
                        name: 'host',
                        label: 'Tunnel host',
                        type: 'text',
                        required: true,
                        placeholder: 'localhost',
                    },
                    {
                        name: 'port',
                        label: 'Tunnel port',
                        type: 'number',
                        required: true,
                        placeholder: '22',
                    },
                    {
                        type: 'select',
                        name: 'auth_type',
                        label: 'Authentication type',
                        required: true,
                        defaultValue: 'password',
                        options: [
                            {
                                label: 'Password',
                                value: 'password',
                                fields: [
                                    {
                                        name: 'username',
                                        label: 'Tunnel username',
                                        type: 'text',
                                        required: true,
                                        placeholder: 'User1',
                                    },
                                    {
                                        name: 'password',
                                        label: 'Tunnel password',
                                        type: 'password',
                                        required: true,
                                        placeholder: '',
                                    },
                                ],
                            },
                            {
                                label: 'Key pair',
                                value: 'keypair',
                                fields: [
                                    {
                                        name: 'username',
                                        label: 'Tunnel username',
                                        type: 'text',
                                        required: false,
                                        placeholder: 'User1',
                                    },
                                    {
                                        name: 'private_key',
                                        label: 'Tunnel private key',
                                        type: 'textarea',
                                        required: true,
                                        placeholder: '',
                                    },
                                    {
                                        name: 'passphrase',
                                        label: 'Tunnel passphrase',
                                        type: 'password',
                                        required: false,
                                        placeholder: '',
                                    },
                                ],
                            },
                        ],
                    },
                ],
            },
        ],
    },
    MSSQL: {
        name: 'MSSQL',
        label: 'MS SQL Server',
        caption: (
            <>
                Enter your MS SQL Server/Azure SQL Server credentials to automatically pull your SQL data into the
                PostHog Data warehouse.
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
                placeholder: '1433',
            },
            {
                name: 'dbname',
                label: 'Database',
                type: 'text',
                required: true,
                placeholder: 'msdb',
            },
            {
                name: 'user',
                label: 'User',
                type: 'text',
                required: true,
                placeholder: 'sa',
            },
            {
                name: 'password',
                label: 'Password',
                type: 'password',
                required: true,
                placeholder: '',
            },
            {
                name: 'schema',
                label: 'Schema',
                type: 'text',
                required: true,
                placeholder: 'dbo',
            },
            {
                name: 'ssh-tunnel',
                label: 'Use SSH tunnel?',
                type: 'switch-group',
                default: false,
                fields: [
                    {
                        name: 'host',
                        label: 'Tunnel host',
                        type: 'text',
                        required: true,
                        placeholder: 'localhost',
                    },
                    {
                        name: 'port',
                        label: 'Tunnel port',
                        type: 'number',
                        required: true,
                        placeholder: '22',
                    },
                    {
                        type: 'select',
                        name: 'auth_type',
                        label: 'Authentication type',
                        required: true,
                        defaultValue: 'password',
                        options: [
                            {
                                label: 'Password',
                                value: 'password',
                                fields: [
                                    {
                                        name: 'username',
                                        label: 'Tunnel username',
                                        type: 'text',
                                        required: true,
                                        placeholder: 'User1',
                                    },
                                    {
                                        name: 'password',
                                        label: 'Tunnel password',
                                        type: 'password',
                                        required: true,
                                        placeholder: '',
                                    },
                                ],
                            },
                            {
                                label: 'Key pair',
                                value: 'keypair',
                                fields: [
                                    {
                                        name: 'username',
                                        label: 'Tunnel username',
                                        type: 'text',
                                        required: false,
                                        placeholder: 'User1',
                                    },
                                    {
                                        name: 'private_key',
                                        label: 'Tunnel private key',
                                        type: 'textarea',
                                        required: true,
                                        placeholder: '',
                                    },
                                    {
                                        name: 'passphrase',
                                        label: 'Tunnel passphrase',
                                        type: 'password',
                                        required: false,
                                        placeholder: '',
                                    },
                                ],
                            },
                        ],
                    },
                ],
            },
        ],
    },
    Snowflake: {
        name: 'Snowflake',
        caption: (
            <>
                Enter your Snowflake credentials to automatically pull your Snowflake data into the PostHog Data
                warehouse.
            </>
        ),
        fields: [
            {
                name: 'account_id',
                label: 'Account id',
                type: 'text',
                required: true,
                placeholder: '',
            },
            {
                name: 'database',
                label: 'Database',
                type: 'text',
                required: true,
                placeholder: 'snowflake_sample_data',
            },
            {
                name: 'warehouse',
                label: 'Warehouse',
                type: 'text',
                required: true,
                placeholder: 'COMPUTE_WAREHOUSE',
            },
            {
                name: 'user',
                label: 'User',
                type: 'text',
                required: true,
                placeholder: 'user',
            },
            {
                name: 'password',
                label: 'Password',
                type: 'password',
                required: true,
                placeholder: '',
            },
            {
                name: 'role',
                label: 'Role (optional)',
                type: 'text',
                required: false,
                placeholder: 'ACCOUNTADMIN',
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
                label: 'Zendesk subdomain',
                type: 'text',
                required: true,
                placeholder: '',
            },
            {
                name: 'api_key',
                label: 'API key',
                type: 'text',
                required: true,
                placeholder: '',
            },
            {
                name: 'email_address',
                label: 'Zendesk email address',
                type: 'email',
                required: true,
                placeholder: '',
            },
        ],
    },
    Salesforce: {
        name: 'Salesforce',
        fields: [
            {
                name: 'integration_id',
                label: 'Salesforce account',
                type: 'oauth',
                required: true,
            },
        ],
        caption: 'Select an existing Salesforce account to link to PostHog or create a new connection',
    },
}

export const buildKeaFormDefaultFromSourceDetails = (
    sourceDetails: Record<string, SourceConfig>
): Record<string, any> => {
    const fieldDefaults = (field: SourceFieldConfig, obj: Record<string, any>): void => {
        if (field.type === 'switch-group') {
            obj[field.name] = {}
            obj[field.name]['enabled'] = field.default
            field.fields.forEach((f) => fieldDefaults(f, obj[field.name]))
            return
        }

        if (field.type === 'select') {
            const hasOptionFields = !!field.options.filter((n) => (n.fields?.length ?? 0) > 0).length
            if (hasOptionFields) {
                obj[field.name] = {}
                obj[field.name]['selection'] = field.defaultValue
                field.options.flatMap((n) => n.fields ?? []).forEach((f) => fieldDefaults(f, obj[field.name]))
            } else {
                obj[field.name] = field.defaultValue
            }
            return
        }

        // All other types
        obj[field.name] = ''
    }

    const sourceDetailsKeys = Object.keys(sourceDetails)
    const formDefault = sourceDetailsKeys.reduce(
        (defaults, cur) => {
            const fields = sourceDetails[cur].fields
            fields.forEach((f) => fieldDefaults(f, defaults['payload']))

            return defaults
        },
        { prefix: '', payload: {} } as Record<string, any>
    )

    return formDefault
}

const manualLinkSourceMap: Record<ManualLinkSourceType, string> = {
    aws: 'S3',
    'google-cloud': 'Google Cloud Storage',
    'cloudflare-r2': 'Cloudflare R2',
    azure: 'Azure',
}

export interface SourceWizardLogicProps {
    onComplete?: () => void
}

export const sourceWizardLogic = kea<sourceWizardLogicType>([
    path(['scenes', 'data-warehouse', 'external', 'sourceWizardLogic']),
    props({} as SourceWizardLogicProps),
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
        updateSchemaSyncType: (
            schema: ExternalDataSourceSyncSchema,
            syncType: ExternalDataSourceSyncSchema['sync_type'],
            incrementalField: string | null,
            incrementalFieldType: string | null
        ) => ({
            schema,
            syncType,
            incrementalField,
            incrementalFieldType,
        }),
        clearSource: true,
        updateSource: (source: Partial<ExternalDataSourceCreatePayload>) => ({ source }),
        createSource: true,
        setIsLoading: (isLoading: boolean) => ({ isLoading }),
        setSourceId: (id: string) => ({ sourceId: id }),
        closeWizard: true,
        cancelWizard: true,
        setStep: (step: number) => ({ step }),
        getDatabaseSchemas: true,
        setManualLinkingProvider: (provider: ManualLinkSourceType) => ({ provider }),
        openSyncMethodModal: (schema: ExternalDataSourceSyncSchema) => ({ schema }),
        cancelSyncMethodModal: true,
    }),
    connect({
        values: [
            dataWarehouseTableLogic,
            ['tableLoading'],
            dataWarehouseSettingsLogic,
            ['dataWarehouseSources'],
            preflightLogic,
            ['preflight'],
            featureFlagLogic,
            ['featureFlags'],
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
            null as ManualLinkSourceType | null,
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
                updateSchemaSyncType: (state, { schema, syncType, incrementalField, incrementalFieldType }) => {
                    const newSchema = state.map((s) => ({
                        ...s,
                        sync_type: s.table === schema.table ? syncType : s.sync_type,
                        incremental_field: s.table === schema.table ? incrementalField : s.incremental_field,
                        incremental_field_type:
                            s.table === schema.table ? incrementalFieldType : s.incremental_field_type,
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
        syncMethodModalOpen: [
            false as boolean,
            {
                openSyncMethodModal: () => true,
                cancelSyncMethodModal: () => false,
            },
        ],
        currentSyncMethodModalSchema: [
            null as ExternalDataSourceSyncSchema | null,
            {
                openSyncMethodModal: (_, { schema }) => schema,
                cancelSyncMethodModal: () => null,
                updateSchemaSyncType: (_, { schema, syncType, incrementalField, incrementalFieldType }) => ({
                    ...schema,
                    sync_type: syncType,
                    incremental_field: incrementalField,
                    incremental_field_type: incrementalFieldType,
                }),
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
            (s) => [s.currentStep, s.isManualLinkingSelected, s.databaseSchema],
            (currentStep, isManualLinkingSelected, databaseSchema): boolean => {
                if (isManualLinkingSelected && currentStep === 1) {
                    return false
                }

                if (!isManualLinkingSelected && currentStep === 3) {
                    if (databaseSchema.filter((n) => n.should_sync).length === 0) {
                        return false
                    }

                    return databaseSchema.filter((n) => n.should_sync && !n.sync_type).length === 0
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
            (s) => [s.currentStep, s.isManualLinkingSelected, (_, props) => props.onComplete],
            (currentStep, isManualLinkingSelected, onComplete): string => {
                if (currentStep === 3 && isManualLinkingSelected) {
                    return 'Link'
                }

                if (currentStep === 3) {
                    return 'Import'
                }

                if (currentStep === 4) {
                    if (onComplete) {
                        return 'Next'
                    }
                    return 'Return to sources'
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
            (s) => [s.dataWarehouseSources, s.featureFlags],
            (sources, featureFlags): SourceConfig[] => {
                const connectors = Object.values(SOURCE_DETAILS).map((connector) => ({
                    ...connector,
                    disabledReason:
                        sources && sources.results.find((source) => source.source_type === connector.name)
                            ? 'Already linked'
                            : null,
                }))

                if (!featureFlags[FEATURE_FLAGS.MSSQL_SOURCE]) {
                    return connectors.filter((n) => n.name !== 'MSSQL')
                }

                return connectors
            },
        ],
        manualConnectors: [
            () => [],
            () =>
                manualLinkSources.map((source) => ({
                    name: manualLinkSourceMap[source],
                    type: source,
                })),
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
                    return ''
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
                    return "Sit tight as we import your data! After it's done, you will be able to query it in PostHog."
                }

                return ''
            },
        ],
        // determines if the wizard is wrapped in another component
        isWrapped: [() => [(_, props) => props.onComplete], (onComplete) => !!onComplete],
    }),
    listeners(({ actions, values, props }) => ({
        onBack: () => {
            if (values.currentStep <= 1) {
                actions.onClear()
            }
        },
        onClear: () => {
            actions.selectConnector(null)
            actions.resetSourceConnectionDetails()
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
            } else if (values.currentStep === 2 && values.isManualLinkFormVisible) {
                dataWarehouseTableLogic.actions.submitTable()
                posthog.capture('source created', { sourceType: 'Manual' })
            }

            if (values.currentStep === 3 && values.selectedConnector?.name) {
                actions.updateSource({
                    payload: {
                        schemas: values.databaseSchema.map((schema) => ({
                            name: schema.table,
                            should_sync: schema.should_sync,
                            sync_type: schema.sync_type,
                            incremental_field: schema.incremental_field,
                            incremental_field_type: schema.incremental_field_type,
                        })),
                    },
                })
                actions.setIsLoading(true)
                actions.createSource()
                posthog.capture('source created', { sourceType: values.selectedConnector.name })
            }

            if (values.currentStep === 4) {
                if (props.onComplete) {
                    props.onComplete()
                } else {
                    actions.closeWizard()
                }
            }
        },
        createTableSuccess: () => {
            actions.cancelWizard()
        },
        closeWizard: () => {
            actions.cancelWizard()
            router.actions.push(urls.pipeline(PipelineTab.Sources))
        },
        cancelWizard: () => {
            actions.onClear()
            actions.clearSource()
            actions.loadSources(null)
            actions.resetSourceConnectionDetails()
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
                case 'salesforce': {
                    actions.updateSource({
                        source_type: 'Salesforce',
                    })
                    break
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

                if (((e.data?.message as string | undefined) ?? '').indexOf('Invalid credentials') != -1) {
                    posthog.capture('warehouse credentials invalid', { sourceType: values.selectedConnector.name })
                }
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
            if (kind === 'salesforce') {
                router.actions.push(urls.dataWarehouseTable(), {
                    kind,
                })
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
            if (searchParams.kind == 'salesforce') {
                actions.selectConnector(SOURCE_DETAILS['Salesforce'])
                actions.handleRedirect(searchParams.kind, {})
                actions.setStep(2)
            }
        },
    })),
    forms(({ actions, values }) => ({
        sourceConnectionDetails: {
            defaults: buildKeaFormDefaultFromSourceDetails(SOURCE_DETAILS),
            errors: (sourceValues) => {
                return getErrorsForFields(values.selectedConnector?.fields ?? [], sourceValues as any)
            },
            submit: async (sourceValues) => {
                if (values.selectedConnector) {
                    const payload = {
                        ...sourceValues,
                        source_type: values.selectedConnector.name,
                    }
                    actions.setIsLoading(true)

                    try {
                        await api.externalDataSources.source_prefix(payload.source_type, sourceValues.prefix)

                        const payloadKeys = (values.selectedConnector?.fields ?? []).map((n) => n.name)

                        // Only store the keys of the source type we're using
                        actions.updateSource({
                            ...payload,
                            payload: {
                                source_type: values.selectedConnector.name,
                                ...payloadKeys.reduce((acc, cur) => {
                                    acc[cur] = payload['payload'][cur]
                                    return acc
                                }, {} as Record<string, any>),
                            },
                        })

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

export const getErrorsForFields = (
    fields: SourceFieldConfig[],
    values: { prefix: string; payload: Record<string, any> } | undefined
): Record<string, any> => {
    const errors: Record<string, any> = {
        payload: {},
    }

    // Prefix errors
    if (!/^[a-zA-Z0-9_-]*$/.test(values?.prefix ?? '')) {
        errors['prefix'] = "Please enter a valid prefix (only letters, numbers, and '_' or '-')."
    }

    // Payload errors
    const validateField = (
        field: SourceFieldConfig,
        valueObj: Record<string, any>,
        errorsObj: Record<string, any>
    ): void => {
        if (field.type === 'switch-group') {
            if (valueObj[field.name]?.['enabled']) {
                errorsObj[field.name] = {}
                field.fields.forEach((f) => validateField(f, valueObj[field.name], errorsObj[field.name]))
            }

            return
        }

        if (field.type === 'select') {
            const hasOptionFields = !!field.options.filter((n) => (n.fields?.length ?? 0) > 0).length
            if (!hasOptionFields) {
                if (field.required && !valueObj[field.name]) {
                    errorsObj[field.name] = `Please select a ${field.label.toLowerCase()}`
                }
            } else {
                errorsObj[field.name] = {}
                const selection = valueObj[field.name]['selection']
                field.options
                    .find((n) => n.value === selection)
                    ?.fields?.forEach((f) => validateField(f, valueObj[field.name], errorsObj[field.name]))
            }
            return
        }

        // All other types
        if (field.required && !valueObj[field.name]) {
            errorsObj[field.name] = `Please enter a ${field.label.toLowerCase()}`
        }
    }

    for (const field of fields) {
        validateField(field, values?.payload ?? {}, errors['payload'])
    }

    return errors
}
