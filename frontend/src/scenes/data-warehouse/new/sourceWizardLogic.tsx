import { lemonToast, Link } from '@posthog/lemon-ui'
import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { ProductIntentContext } from 'lib/utils/product-intents'
import posthog from 'posthog-js'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { activationLogic, ActivationTask } from '~/layout/navigation-3000/sidepanel/panels/activation/activationLogic'
import {
    Breadcrumb,
    ExternalDataSourceCreatePayload,
    externalDataSources,
    ExternalDataSourceSyncSchema,
    ExternalDataSourceType,
    manualLinkSources,
    ManualLinkSourceType,
    PipelineStage,
    PipelineTab,
    ProductKey,
    SourceConfig,
    SourceFieldConfig,
} from '~/types'

import { dataWarehouseSettingsLogic } from '../settings/dataWarehouseSettingsLogic'
import { dataWarehouseTableLogic } from './dataWarehouseTableLogic'
import type { sourceWizardLogicType } from './sourceWizardLogicType'

const StripeCaption = (): JSX.Element => (
    <>
        Enter your Stripe credentials to automatically pull your Stripe data into the PostHog Data warehouse.
        <br />
        You can find your account ID{' '}
        <Link to="https://dashboard.stripe.com/settings/account" target="_blank">
            in your Stripe dashboard
        </Link>
        , and create a secret key{' '}
        <Link to="https://dashboard.stripe.com/apikeys/create" target="_blank">
            here
        </Link>
        .
        <br />
        <br />
        Currently, <strong>read permissions are required</strong> for the following resources:
        <ul className="list-disc list-inside">
            <li>
                Under the <strong>Core</strong> resource type, select <i>read</i> for{' '}
                <strong>Balance transaction sources</strong>, <strong>Charges</strong>, <strong>Customer</strong>,{' '}
                <strong>Product</strong>, <strong>Disputes</strong>, and <strong>Payouts</strong>
            </li>
            <li>
                Under the <strong>Billing</strong> resource type, select <i>read</i> for <strong>Invoice</strong>,{' '}
                <strong>Price</strong>, <strong>Subscription</strong>, and <strong>Credit notes</strong>
            </li>
            <li>
                Under the <strong>Connected</strong> resource type, select <i>read</i> for the{' '}
                <strong>entire resource</strong>
            </li>
        </ul>
    </>
)

export const getHubspotRedirectUri = (): string =>
    `${window.location.origin}${urls.pipelineNodeNew(PipelineStage.Source, { source: 'Hubspot' })}`

export const SOURCE_DETAILS: Record<ExternalDataSourceType, SourceConfig> = {
    Stripe: {
        name: 'Stripe',
        caption: <StripeCaption />,
        fields: [
            {
                name: 'stripe_account_id',
                label: 'Account id',
                type: 'text',
                required: false,
                placeholder: 'stripe_account_id',
            },
            {
                name: 'stripe_secret_key',
                label: 'API key',
                type: 'password',
                required: true,
                placeholder: 'rk_live_...',
            },
        ],
    },
    Hubspot: {
        name: 'Hubspot',
        fields: [],
        caption: 'Successfully authenticated with Hubspot. Please continue here to complete the source setup',
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
                name: 'connection_string',
                label: 'Connection string (optional)',
                type: 'text',
                required: false,
                placeholder: 'postgresql://user:password@localhost:5432/database',
            },
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
                name: 'database',
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
                name: 'database',
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
                type: 'select',
                name: 'using_ssl',
                label: 'Use SSL?',
                defaultValue: '1',
                required: true,
                options: [
                    {
                        value: '1',
                        label: 'Yes',
                    },
                    {
                        value: '0',
                        label: 'No',
                    },
                ],
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
        label: 'Microsoft SQL Server',
        caption: (
            <>
                Enter your Microsoft SQL Server/Azure SQL Server credentials to automatically pull your SQL data into
                the PostHog Data warehouse.
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
                name: 'database',
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
                                label: 'Username',
                                type: 'text',
                                required: true,
                                placeholder: 'User1',
                            },
                            {
                                name: 'password',
                                label: 'Password',
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
                                label: 'Username',
                                type: 'text',
                                required: true,
                                placeholder: 'User1',
                            },
                            {
                                name: 'private_key',
                                label: 'Private key',
                                type: 'textarea',
                                required: true,
                                placeholder: '',
                            },
                            {
                                name: 'passphrase',
                                label: 'Passphrase',
                                type: 'password',
                                required: false,
                                placeholder: '',
                            },
                        ],
                    },
                ],
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
                name: 'salesforce_integration_id',
                label: 'Salesforce account',
                type: 'oauth',
                required: true,
                kind: 'salesforce',
            },
        ],
        caption: 'Select an existing Salesforce account to link to PostHog or create a new connection',
    },
    Vitally: {
        name: 'Vitally',
        fields: [
            {
                name: 'secret_token',
                label: 'Secret token',
                type: 'text',
                required: true,
                placeholder: 'sk_live_...',
            },
            {
                type: 'select',
                name: 'region',
                label: 'Vitally region',
                required: true,
                defaultValue: 'EU',
                options: [
                    {
                        label: 'EU',
                        value: 'EU',
                    },
                    {
                        label: 'US',
                        value: 'US',
                        fields: [
                            {
                                name: 'subdomain',
                                label: 'Vitally subdomain',
                                type: 'text',
                                required: true,
                                placeholder: '',
                            },
                        ],
                    },
                ],
            },
        ],
        caption: '',
    },
    BigQuery: {
        name: 'BigQuery',
        fields: [
            {
                type: 'file-upload',
                name: 'key_file',
                label: 'Google Cloud JSON key file',
                fileFormat: '.json',
                required: true,
            },
            {
                type: 'text',
                name: 'dataset_id',
                label: 'Dataset ID',
                required: true,
                placeholder: '',
            },
            {
                type: 'switch-group',
                name: 'temporary-dataset',
                label: 'Use a different dataset for the temporary tables?',
                caption:
                    "We have to create and delete temporary tables when querying your data, this is a requirement of querying large BigQuery tables. We can use a different dataset if you'd like to limit the permissions available to the service account provided.",
                default: false,
                fields: [
                    {
                        type: 'text',
                        name: 'temporary_dataset_id',
                        label: 'Dataset ID for temporary tables',
                        required: true,
                        placeholder: '',
                    },
                ],
            },
            {
                type: 'switch-group',
                name: 'dataset_project',
                label: 'Use a different project for the dataset than your service account project?',
                caption:
                    "If the dataset you're wanting to sync exists in a different project than that of your service account, use this to provide the project ID of the BigQuery dataset.",
                default: false,
                fields: [
                    {
                        type: 'text',
                        name: 'dataset_project_id',
                        label: 'Project ID for dataset',
                        required: true,
                        placeholder: '',
                    },
                ],
            },
        ],
        caption: '',
    },
    Chargebee: {
        name: 'Chargebee',
        fields: [
            {
                name: 'api_key',
                label: 'API key',
                type: 'text',
                required: true,
                placeholder: '',
            },
            {
                type: 'text',
                name: 'site_name',
                label: 'Site name (subdomain)',
                required: true,
                placeholder: '',
            },
        ],
        caption: '',
    },
    TemporalIO: {
        name: 'TemporalIO',
        label: 'Temporal.io',
        fields: [
            {
                name: 'host',
                label: 'Host',
                type: 'text',
                required: true,
                placeholder: '',
            },
            {
                name: 'port',
                label: 'Port',
                type: 'text',
                required: true,
                placeholder: '',
            },
            {
                name: 'namespace',
                label: 'Namespace',
                type: 'text',
                required: true,
                placeholder: '',
            },
            {
                name: 'encryption_key',
                label: 'Encryption key',
                type: 'text',
                required: false,
                placeholder: '',
            },
            {
                name: 'server_client_root_ca',
                label: 'Server client root CA',
                type: 'textarea',
                required: true,
                placeholder: '',
            },
            {
                name: 'client_certificate',
                label: 'Client certificate',
                type: 'textarea',
                required: true,
                placeholder: '',
            },
            {
                name: 'client_private_key',
                label: 'Client private key',
                type: 'textarea',
                required: true,
                placeholder: '',
            },
        ],
        caption: '',
    },
    GoogleAds: {
        name: 'GoogleAds',
        label: 'Google Ads',
        betaSource: true,
        caption: (
            <>
                Ensure you have granted PostHog access to your Google Ads account, learn how to do this in{' '}
                <Link to="https://posthog.com/docs/cdp/sources/google-ads" target="_blank">
                    the docs
                </Link>
                .
            </>
        ),
        fields: [
            {
                name: 'customer_id',
                label: 'Customer ID',
                type: 'text',
                required: true,
                placeholder: '',
            },
            {
                name: 'google_ads_integration_id',
                label: 'Google Ads account',
                type: 'oauth',
                required: true,
                kind: 'google-ads',
            },
        ],
    },
    DoIt: {
        name: 'DoIt',
        label: 'DoIt',
        caption: '',
        fields: [
            {
                name: 'api_key',
                label: 'API key',
                type: 'text',
                required: true,
                placeholder: '',
            },
        ],
    },
    GoogleSheets: {
        name: 'GoogleSheets',
        label: 'Google Sheets',
        caption: (
            <>
                Ensure you have granted PostHog access to your Google Sheet as instructed in the
                <Link to="https://posthog.com/docs/cdp/sources/google-sheets" target="_blank">
                    documentation
                </Link>
                .
            </>
        ),
        fields: [
            {
                name: 'spreadsheet_url',
                label: 'Spreadsheet URL',
                type: 'text',
                required: true,
                placeholder: '',
            },
        ],
        betaSource: true,
    },
    MongoDB: {
        name: 'MongoDB',
        label: 'MongoDB',
        caption: (
            <>
                Enter your MongoDB connection string to automatically pull your MongoDB data into the PostHog Data
                warehouse.
            </>
        ),
        fields: [
            {
                name: 'connection_string',
                label: 'Connection String',
                type: 'text',
                required: true,
                placeholder: 'mongodb://username:password@host:port/database?authSource=admin',
            },
        ],
        betaSource: true,
    },
    MetaAds: {
        name: 'MetaAds',
        label: 'Meta Ads',
        caption: '',
        fields: [],
        unreleasedSource: true,
    },
    Klaviyo: {
        name: 'Klaviyo',
        label: 'Klaviyo',
        caption: '',
        fields: [],
        unreleasedSource: true,
    },
    Mailchimp: {
        name: 'Mailchimp',
        label: 'Mailchimp',
        caption: '',
        fields: [],
        unreleasedSource: true,
    },
    Braze: {
        name: 'Braze',
        label: 'Braze',
        caption: '',
        fields: [],
        unreleasedSource: true,
    },
    Mailjet: {
        name: 'Mailjet',
        label: 'Mailjet',
        caption: '',
        fields: [],
        unreleasedSource: true,
    },
    Redshift: {
        name: 'Redshift',
        label: 'Redshift',
        caption: '',
        fields: [],
        unreleasedSource: true,
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
    return sourceDetailsKeys.reduce(
        (defaults, cur) => {
            const fields = sourceDetails[cur].fields
            fields.forEach((f) => fieldDefaults(f, defaults['payload']))

            return defaults
        },
        { prefix: '', payload: {} } as Record<string, any>
    )
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
        handleRedirect: (source: ExternalDataSourceType, searchParams?: any) => ({ source, searchParams }),
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
        updateSyncTimeOfDay: (schema: ExternalDataSourceSyncSchema, syncTimeOfDay: string) => ({
            schema,
            syncTimeOfDay,
        }),
        setIsProjectTime: (isProjectTime: boolean) => ({ isProjectTime }),
    }),
    connect(() => ({
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
            teamLogic,
            ['addProductIntent'],
        ],
    })),
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
                    return state.map((s) => ({
                        ...s,
                        should_sync: s.table === schema.table ? shouldSync : s.should_sync,
                    }))
                },
                updateSyncTimeOfDay: (state, { schema, syncTimeOfDay }) => {
                    return state.map((s) => ({
                        ...s,
                        sync_time_of_day: s.table === schema.table ? syncTimeOfDay : s.sync_time_of_day,
                    }))
                },
                updateSchemaSyncType: (state, { schema, syncType, incrementalField, incrementalFieldType }) => {
                    return state.map((s) => ({
                        ...s,
                        sync_type: s.table === schema.table ? syncType : s.sync_type,
                        incremental_field: s.table === schema.table ? incrementalField : s.incremental_field,
                        incremental_field_type:
                            s.table === schema.table ? incrementalFieldType : s.incremental_field_type,
                    }))
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
                            ...state.payload,
                            ...source.payload,
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
        isProjectTime: [
            false as boolean,
            {
                setIsProjectTime: (_, { isProjectTime }) => isProjectTime,
            },
        ],
    }),
    selectors({
        breadcrumbs: [
            (s) => [s.selectedConnector, s.manualLinkingProvider, s.manualConnectors],
            (selectedConnector, manualLinkingProvider, manualConnectors): Breadcrumb[] => {
                return [
                    {
                        key: Scene.Pipeline,
                        name: 'Data pipelines',
                        path: urls.pipeline(PipelineTab.Overview),
                    },
                    {
                        key: [Scene.Pipeline, 'sources'],
                        name: `Sources`,
                        path: urls.pipeline(PipelineTab.Sources),
                    },
                    {
                        key: Scene.DataWarehouseSource,
                        name:
                            selectedConnector?.label ??
                            (manualLinkingProvider
                                ? manualConnectors.find((c) => c.type === manualLinkingProvider)?.name
                                : 'New'),
                    },
                ]
            },
        ],

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
                    existingSource:
                        sources && sources.results.find((source) => source.source_type === connector.name)
                            ? true
                            : false,
                }))
            },
        ],
        manualConnectors: [
            () => [],
            (): { name: string; type: ManualLinkSourceType }[] =>
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
                            sync_time_of_day: schema.sync_time_of_day,
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

                lemonToast.success('New data resource created')

                activationLogic.findMounted()?.actions.markTaskAsCompleted(ActivationTask.ConnectSource)

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
        handleRedirect: async ({ source, searchParams }) => {
            switch (source) {
                case 'Hubspot': {
                    actions.updateSource({
                        source_type: source,
                        payload: {
                            code: searchParams?.code,
                            redirect_uri: getHubspotRedirectUri(),
                        },
                    })
                    return
                }

                default:
                    // By default, we assume the source is a valid external data source
                    if (externalDataSources.includes(source)) {
                        actions.updateSource({
                            source_type: source,
                        })
                    } else {
                        lemonToast.error(`Something went wrong.`)
                    }
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
                const errorMessage = e.data?.message ?? e.message
                lemonToast.error(errorMessage)

                posthog.capture('warehouse credentials invalid', {
                    sourceType: values.selectedConnector.name,
                    errorMessage,
                })
            }

            actions.setIsLoading(false)
        },
        setManualLinkingProvider: () => {
            actions.onNext()
        },
        selectConnector: () => {
            actions.addProductIntent({
                product_type: ProductKey.DATA_WAREHOUSE,
                intent_context: ProductIntentContext.SELECTED_CONNECTOR,
            })
        },
    })),
    urlToAction(({ actions, values }) => {
        const handleUrlChange = (_: Record<string, string | undefined>, searchParams: Record<string, string>): void => {
            const kind = searchParams.kind?.toLowerCase()
            const source = values.connectors.find((s) => s.name.toLowerCase() === kind)
            const manualSource = values.manualConnectors.find((s) => s.type.toLowerCase() === kind)

            if (manualSource) {
                actions.toggleManualLinkFormVisible(true)
                actions.setManualLinkingProvider(manualSource.type)
                return
            }

            if (source?.name === 'Hubspot') {
                if (searchParams.code) {
                    actions.selectConnector(source)
                    actions.handleRedirect(source.name, {
                        code: searchParams.code,
                    })
                    actions.setStep(2)
                    return
                }

                window.open(values.addToHubspotButtonUrl() as string, '_self')
                return
            }

            if (source) {
                actions.selectConnector(source)
                actions.handleRedirect(source.name)
                actions.setStep(2)
                return
            }

            actions.selectConnector(null)
            actions.setStep(1)
        }

        return {
            [urls.dataWarehouseSourceNew()]: handleUrlChange,
            [urls.pipelineNodeNew(PipelineStage.Source)]: handleUrlChange,
        }
    }),

    forms(({ actions, values }) => ({
        sourceConnectionDetails: {
            defaults: buildKeaFormDefaultFromSourceDetails(SOURCE_DETAILS),
            errors: (sourceValues) => {
                const errors = getErrorsForFields(values.selectedConnector?.fields ?? [], sourceValues as any)

                if (values.sourceConnectionDetailsManualErrors.prefix && sourceValues.prefix) {
                    actions.setSourceConnectionDetailsManualErrors({
                        prefix: undefined,
                    })
                }

                return errors
            },
            submit: async (sourceValues) => {
                if (values.selectedConnector) {
                    const payload: Record<string, any> = {
                        ...sourceValues,
                        source_type: values.selectedConnector.name,
                    }
                    actions.setIsLoading(true)

                    try {
                        await api.externalDataSources.source_prefix(payload.source_type, sourceValues.prefix)

                        const payloadKeys = (values.selectedConnector?.fields ?? []).map((n) => ({
                            name: n.name,
                            type: n.type,
                        }))

                        const fieldPayload: Record<string, any> = {
                            source_type: values.selectedConnector.name,
                        }

                        for (const { name, type } of payloadKeys) {
                            if (type === 'file-upload') {
                                try {
                                    // Assumes we're loading a JSON file
                                    const loadedFile: string = await new Promise((resolve, reject) => {
                                        const fileReader = new FileReader()
                                        fileReader.onload = (e) => resolve(e.target?.result as string)
                                        fileReader.onerror = (e) => reject(e)
                                        fileReader.readAsText(payload['payload'][name][0])
                                    })
                                    fieldPayload[name] = JSON.parse(loadedFile)
                                } catch {
                                    return lemonToast.error('File is not valid')
                                }
                            } else {
                                fieldPayload[name] = payload['payload'][name]
                            }
                        }

                        // Only store the keys of the source type we're using
                        actions.updateSource({
                            ...payload,
                            payload: {
                                source_type: values.selectedConnector.name,
                                ...fieldPayload,
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
            // handle string value coming down from the backend for an update
            if (valueObj[field.name]?.['enabled'] && valueObj[field.name]?.['enabled'] !== 'False') {
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
                const selection = valueObj[field.name]?.['selection']
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
