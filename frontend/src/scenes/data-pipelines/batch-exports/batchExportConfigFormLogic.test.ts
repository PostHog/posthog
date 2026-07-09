import { router } from 'kea-router'
import { expectLogic, partial } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { MockResolverInfo } from '~/mocks/utils'
import { initKeaTests } from '~/test/init'
import { BatchExportConfiguration } from '~/types'

import {
    BatchExportConfigFormLogicProps,
    batchExportConfigFormLogic,
    getDefaultConfiguration,
} from './batchExportConfigFormLogic'

// Builds a BatchExportConfiguration with shared defaults so each fixture only declares its destination.
function fixture<T extends BatchExportConfiguration['destination']>(
    id: string,
    name: string,
    destination: T
): BatchExportConfiguration {
    return {
        id,
        team_id: 997,
        name,
        destination: destination as BatchExportConfiguration['destination'],
        interval: 'hour',
        timezone: null,
        offset_day: null,
        offset_hour: null,
        created_at: '2024-01-01T00:00:00Z',
        start_at: null,
        end_at: null,
        paused: false,
        model: 'events',
        filters: [],
    }
}

const S3_BATCH_EXPORT = fixture('test-s3-id', 'S3 Export', {
    type: 'S3',
    config: {
        bucket_name: 'test-bucket',
        region: 'us-east-1',
        prefix: 'posthog-events/',
        aws_access_key_id: 'AKIAIOSFODNN7EXAMPLE',
        aws_secret_access_key: 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY',
        exclude_events: [],
        include_events: [],
        compression: 'gzip',
        encryption: null,
        kms_key_id: null,
        endpoint_url: null,
        file_format: 'Parquet',
        max_file_size_mb: null,
        use_virtual_style_addressing: false,
    },
})

const AWS_S3_BATCH_EXPORT = fixture('test-aws-s3-id', 'AWS S3 Export', {
    type: 'AwsS3',
    config: {
        bucket_name: 'test-bucket',
        region: 'us-east-1',
        prefix: 'posthog-events/',
        aws_access_key_id: 'AKIAIOSFODNN7EXAMPLE',
        aws_secret_access_key: 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY',
        exclude_events: [],
        include_events: [],
        compression: 'zstd',
        encryption: null,
        kms_key_id: null,
        file_format: 'Parquet',
        max_file_size_mb: null,
    },
})

const S3_COMPATIBLE_BATCH_EXPORT = fixture('test-s3-compatible-id', 'S3-compatible Export', {
    type: 'S3Compatible',
    config: {
        bucket_name: 'test-bucket',
        region: 'auto',
        prefix: 'posthog-events/',
        aws_access_key_id: 'AKIAIOSFODNN7EXAMPLE',
        aws_secret_access_key: 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY',
        exclude_events: [],
        include_events: [],
        compression: 'zstd',
        endpoint_url: 'https://test-minio-host:9000',
        use_virtual_style_addressing: false,
        file_format: 'Parquet',
        max_file_size_mb: null,
    },
})

// BigQuery exports are integration-backed: the config carries `integration` and the
// credentials live on the integration, not in the config.
const BIGQUERY_BATCH_EXPORT = fixture('test-bq-id', 'BigQuery Export', {
    type: 'BigQuery',
    integration: 7,
    config: {
        dataset_id: 'test_dataset',
        table_id: 'events',
        exclude_events: [],
        include_events: [],
        use_json_type: false,
    },
})

// A BigQuery export whose stored config still carries pre-Integration leftovers: the frontend-only
// `json_config_file` and credentials that now live on the integration. These must be stripped on
// save — the backend rejects any config key not on the destination's allowlist.
const BIGQUERY_STALE_BATCH_EXPORT = fixture('test-bq-stale-id', 'BigQuery Stale Export', {
    type: 'BigQuery',
    integration: 7,
    config: {
        dataset_id: 'test_dataset',
        table_id: 'events',
        use_json_type: false,
        exclude_events: [],
        include_events: [],
        json_config_file: [{}],
        private_key: 'stale-private-key',
        project_id: 'stale-project',
    } as any,
})

const POSTGRES_BATCH_EXPORT = fixture('fixture-postgres', 'Postgres Export', {
    type: 'Postgres',
    config: {
        user: 'pg-user',
        password: 'pg-pass',
        host: 'pg-host',
        port: 5432,
        database: 'pg-db',
        schema: 'public',
        table_name: 'events',
        has_self_signed_cert: false,
        exclude_events: [],
        include_events: [],
    },
})

const SNOWFLAKE_PASSWORD_BATCH_EXPORT = fixture('fixture-snowflake-password', 'Snowflake Password Export', {
    type: 'Snowflake',
    config: {
        account: 'sf-account',
        database: 'sf-db',
        warehouse: 'sf-wh',
        user: 'sf-user',
        authentication_type: 'password',
        password: 'sf-pass',
        private_key: null,
        private_key_passphrase: null,
        schema: 'public',
        table_name: 'events',
        role: null,
        exclude_events: [],
        include_events: [],
    },
})

const SNOWFLAKE_KEYPAIR_BATCH_EXPORT = fixture('fixture-snowflake-keypair', 'Snowflake Keypair Export', {
    type: 'Snowflake',
    config: {
        account: 'sf-account',
        database: 'sf-db',
        warehouse: 'sf-wh',
        user: 'sf-user',
        authentication_type: 'keypair',
        password: null,
        private_key: 'priv-key',
        private_key_passphrase: 'priv-pass',
        schema: 'public',
        table_name: 'events',
        role: null,
        exclude_events: [],
        include_events: [],
    },
})

// Note: `authorization_mode` is intentionally absent from these Redshift fixtures' config —
// it is a form-only field and is dropped on save.
const REDSHIFT_INSERT_BATCH_EXPORT = fixture('fixture-redshift-insert', 'Redshift INSERT Export', {
    type: 'Redshift',
    config: {
        user: 'rs-user',
        password: 'rs-pass',
        host: 'rs-host',
        port: 5439,
        database: 'rs-db',
        schema: 'public',
        table_name: 'events',
        properties_data_type: 'SUPER' as any,
        mode: 'INSERT',
        copy_inputs: null,
        exclude_events: [],
        include_events: [],
    } as any,
})

const REDSHIFT_COPY_IAM_BATCH_EXPORT = fixture('fixture-redshift-copy-iam', 'Redshift COPY IAM Export', {
    type: 'Redshift',
    config: {
        user: 'rs-user',
        password: 'rs-pass',
        host: 'rs-host',
        port: 5439,
        database: 'rs-db',
        schema: 'public',
        table_name: 'events',
        properties_data_type: 'SUPER' as any,
        mode: 'COPY',
        copy_inputs: {
            s3_bucket: 'rs-staging',
            s3_key_prefix: 'rs/copy/',
            region_name: 'us-east-1',
            authorization: 'arn:aws:iam::123:role/rs-copy',
            bucket_credentials: {
                aws_access_key_id: 'AKIA-bucket',
                aws_secret_access_key: 'bucket-secret',
            },
        },
        exclude_events: [],
        include_events: [],
    } as any,
})

const REDSHIFT_COPY_CREDENTIALS_BATCH_EXPORT = fixture(
    'fixture-redshift-copy-creds',
    'Redshift COPY Credentials Export',
    {
        type: 'Redshift',
        config: {
            user: 'rs-user',
            password: 'rs-pass',
            host: 'rs-host',
            port: 5439,
            database: 'rs-db',
            schema: 'public',
            table_name: 'events',
            properties_data_type: 'SUPER' as any,
            mode: 'COPY',
            copy_inputs: {
                s3_bucket: 'rs-staging',
                s3_key_prefix: 'rs/copy/',
                region_name: 'us-east-1',
                authorization: {
                    aws_access_key_id: 'AKIA-auth',
                    aws_secret_access_key: 'auth-secret',
                },
                bucket_credentials: {
                    aws_access_key_id: 'AKIA-bucket',
                    aws_secret_access_key: 'bucket-secret',
                },
            },
            exclude_events: [],
            include_events: [],
        } as any,
    }
)

const HTTP_BATCH_EXPORT = fixture('fixture-http', 'HTTP Export', {
    type: 'HTTP',
    config: {
        url: 'https://us.i.posthog.com/batch/',
        token: 'phc_test',
        exclude_events: [],
        include_events: [],
    },
})

const DATABRICKS_BATCH_EXPORT = fixture('fixture-databricks', 'Databricks Export', {
    type: 'Databricks',
    integration: 42,
    config: {
        http_path: '/sql/1.0/warehouses/abc123',
        catalog: 'workspace',
        schema: 'default',
        table_name: 'events',
        use_variant_type: true,
        exclude_events: [],
        include_events: [],
    },
})

const AZUREBLOB_BATCH_EXPORT = fixture('fixture-azureblob', 'Azure Blob Export', {
    type: 'AzureBlob',
    integration: 99,
    config: {
        container_name: 'my-container',
        prefix: 'posthog/events/',
        compression: 'zstd',
        file_format: 'Parquet',
        max_file_size_mb: null,
        exclude_events: [],
        include_events: [],
    },
})

// Single map keyed by id; used to register GET + PATCH mocks dynamically below.
const ALL_BATCH_EXPORTS: BatchExportConfiguration[] = [
    S3_BATCH_EXPORT,
    AWS_S3_BATCH_EXPORT,
    S3_COMPATIBLE_BATCH_EXPORT,
    BIGQUERY_BATCH_EXPORT,
    BIGQUERY_STALE_BATCH_EXPORT,
    POSTGRES_BATCH_EXPORT,
    SNOWFLAKE_PASSWORD_BATCH_EXPORT,
    SNOWFLAKE_KEYPAIR_BATCH_EXPORT,
    REDSHIFT_INSERT_BATCH_EXPORT,
    REDSHIFT_COPY_IAM_BATCH_EXPORT,
    REDSHIFT_COPY_CREDENTIALS_BATCH_EXPORT,
    HTTP_BATCH_EXPORT,
    DATABRICKS_BATCH_EXPORT,
    AZUREBLOB_BATCH_EXPORT,
]

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: {
        error: jest.fn(),
        success: jest.fn(),
    },
}))

jest.mock('lib/utils/product-intents', () => ({
    addProductIntent: jest.fn().mockResolvedValue(null),
}))

describe('batchExportConfigFormLogic', () => {
    let logic: ReturnType<typeof batchExportConfigFormLogic.build>
    let lastPostBody: Record<string, any> | null = null
    let lastPatchBody: Record<string, any> | null = null
    const patchBodiesById: Record<string, Record<string, any>> = {}

    beforeEach(() => {
        lastPostBody = null
        lastPatchBody = null
        for (const id of Object.keys(patchBodiesById)) {
            delete patchBodiesById[id]
        }
        // Register a GET + PATCH mock for every fixture so any round-trip test can load its
        // own fixture by id and look up the captured request body via patchBodiesById[fx.id].
        const getMocks: Record<string, BatchExportConfiguration> = {}
        const patchMocks: Record<string, (info: MockResolverInfo) => Promise<[number, BatchExportConfiguration]>> = {}
        for (const fx of ALL_BATCH_EXPORTS) {
            getMocks[`/api/environments/:team_id/batch_exports/${fx.id}`] = fx
            patchMocks[`/api/environments/:team_id/batch_exports/${fx.id}/`] = async ({ request }) => {
                const body = (await request.json()) as Record<string, any>
                lastPatchBody = body
                patchBodiesById[fx.id] = body
                return [200, fx]
            }
        }
        useMocks({
            get: {
                ...getMocks,
                '/api/environments/:team_id/batch_exports/test': { steps: [] },
            },
            post: {
                '/api/environments/:team_id/batch_exports/': async ({ request }) => {
                    lastPostBody = (await request.json()) as Record<string, any>
                    return [200, { ...S3_BATCH_EXPORT, id: 'new-export-id' }]
                },
            },
            patch: patchMocks,
        })
        initKeaTests()
    })

    async function initLogic(props: BatchExportConfigFormLogicProps): Promise<void> {
        await expectLogic(teamLogic).toFinishAllListeners()
        logic = batchExportConfigFormLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    describe('new batch export config initialization', () => {
        it('sets isNew to true and loads defaults', async () => {
            await initLogic({ service: 'S3', id: null })

            await expectLogic(logic).toMatchValues({
                isNew: true,
                configuration: partial({
                    destination: 'S3',
                    file_format: 'Parquet',
                    compression: 'zstd',
                    paused: true,
                    model: 'events',
                }),
            })
        })
    })

    describe('existing batch export config loading', () => {
        it('loads configuration from API', async () => {
            await initLogic({ service: null, id: 'test-s3-id' })

            await expectLogic(logic).toMatchValues({
                isNew: false,
                configuration: partial({
                    destination: 'S3',
                    name: 'S3 Export',
                    bucket_name: 'test-bucket',
                    region: 'us-east-1',
                    prefix: 'posthog-events/',
                }),
            })
        })
    })

    describe('required fields validation', () => {
        const GENERAL_REQUIRED_FIELDS = ['interval', 'name', 'model']
        it.each([
            {
                service: 'S3' as const,
                fields: [
                    'bucket_name',
                    'region',
                    'prefix',
                    'aws_access_key_id',
                    'aws_secret_access_key',
                    'file_format',
                ],
            },
            {
                // New AwsS3 exports authenticate via an integration, not inline credentials.
                service: 'AwsS3' as const,
                fields: ['integration_id', 'bucket_name', 'region', 'prefix', 'file_format'],
            },
            {
                // New S3Compatible exports authenticate via an integration; endpoint_url lives on it.
                service: 'S3Compatible' as const,
                fields: ['integration_id', 'bucket_name', 'region', 'prefix', 'file_format'],
            },
            {
                service: 'Postgres' as const,
                fields: ['integration_id', 'database', 'schema', 'table_name'],
            },
            {
                service: 'Redshift' as const,
                fields: ['user', 'password', 'host', 'port', 'database', 'schema', 'table_name'],
            },
            {
                service: 'Snowflake' as const,
                fields: ['account', 'database', 'warehouse', 'user', 'password', 'schema', 'table_name'],
            },
            { service: 'BigQuery' as const, fields: ['integration_id', 'dataset_id', 'table_id'] },
            { service: 'HTTP' as const, fields: ['url', 'token'] },
            {
                service: 'Databricks' as const,
                fields: ['integration_id', 'http_path', 'catalog', 'schema', 'table_name'],
            },
            { service: 'AzureBlob' as const, fields: ['integration_id', 'container_name', 'file_format'] },
        ])('rejects empty form for $service', async ({ service, fields }) => {
            await initLogic({ service, id: null })

            await expectLogic(logic, () => {
                logic.actions.submitConfiguration()
            }).toDispatchActions(['submitConfiguration', 'submitConfigurationFailure'])

            const defaults = getDefaultConfiguration(service)
            const errors = logic.values.configurationErrors
            for (const field of [...GENERAL_REQUIRED_FIELDS, ...fields]) {
                // Fields pre-filled by getDefaultConfiguration (name, model, file_format) shouldn't
                // error; every other required field must surface a "required" message.
                const expectedError = defaults[field] ? undefined : 'This field is required'
                expect(errors[field]).toBe(expectedError)
            }
        })
    })

    describe('S3 bucket name validation', () => {
        it.each([
            { bucket: 'MyBucket', error: 'Bucket name must be lowercase' },
            { bucket: 'my bucket', error: 'Bucket name cannot contain whitespace' },
            { bucket: 'my..bucket', error: 'Bucket name cannot contain consecutive periods' },
            { bucket: '192.168.1.1', error: 'Bucket name cannot be formatted as an IP address' },
            { bucket: 'my-valid-bucket', error: undefined },
            { bucket: 'my.valid.bucket', error: undefined },
        ])('bucket "$bucket" → $error', async ({ bucket, error }) => {
            await initLogic({ service: 'S3', id: null })

            logic.actions.setConfigurationValues({
                ...logic.values.configuration,
                bucket_name: bucket,
                region: 'us-east-1',
                prefix: 'test/',
                aws_access_key_id: 'AKIAIOSFODNN7EXAMPLE',
                aws_secret_access_key: 'secret',
                file_format: 'Parquet',
                interval: 'hour',
                name: 'Test Export',
                model: 'events',
            })

            logic.actions.submitConfiguration()
            await expectLogic(logic).toFinishAllListeners()

            const errors = logic.values.configurationErrors
            expect(errors.bucket_name).toBe(error)
        })
    })

    describe('AzureBlob container name validation', () => {
        it.each([
            {
                container: 'My-Container',
                error: 'Must be lowercase letters, numbers, and hyphens; start and end with letter or number',
            },
            { container: 'my--container', error: 'Cannot contain consecutive hyphens' },
            { container: 'my-container', error: undefined },
            { container: 'mycontainer1', error: undefined },
        ])('container "$container" → $error', async ({ container, error }) => {
            await initLogic({ service: 'AzureBlob', id: null })

            logic.actions.setConfigurationValues({
                ...logic.values.configuration,
                integration_id: 11,
                container_name: container,
                interval: 'hour',
                name: 'Test Export',
                model: 'events',
            })

            logic.actions.submitConfiguration()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.configurationErrors.container_name).toBe(error)
        })
    })

    describe('compression resets when file_format changes', () => {
        it.each([
            { newFormat: 'JSONLines', expected: null },
            { newFormat: 'Parquet', expected: 'zstd' },
        ])('new export: switching to $newFormat sets compression to $expected', async ({ newFormat, expected }) => {
            await initLogic({ service: 'S3', id: null })

            logic.actions.setConfigurationValue('file_format', newFormat)
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.configuration.compression).toBe(expected)
        })

        it.each([
            { startCompression: 'snappy', expected: null },
            { startCompression: 'gzip', expected: 'gzip' },
        ])(
            'existing export: Parquet/$startCompression -> JSONLines yields $expected',
            async ({ startCompression, expected }) => {
                await initLogic({ service: null, id: S3_BATCH_EXPORT.id })
                logic.actions.setConfigurationValues({ compression: startCompression })
                await expectLogic(logic).toFinishAllListeners()

                logic.actions.setConfigurationValue('file_format', 'JSONLines')
                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values.configuration.compression).toBe(expected)
            }
        )

        it('existing export: Parquet/zstd -> JSONLines -> Parquet restores the saved zstd codec', async () => {
            // AWS_S3_BATCH_EXPORT is saved with Parquet/zstd; zstd is invalid for JSONLines, so it's
            // cleared on the way out and must come back from the saved config — not default to zstd by
            // coincidence.
            await initLogic({ service: null, id: AWS_S3_BATCH_EXPORT.id })
            expect(logic.values.configuration.compression).toBe('zstd')

            logic.actions.setConfigurationValue('file_format', 'JSONLines')
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.configuration.compression).toBeNull()

            logic.actions.setConfigurationValue('file_format', 'Parquet')
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.configuration.compression).toBe('zstd')
        })

        it('existing export: Parquet/gzip survives a JSONLines round-trip (valid for both formats)', async () => {
            await initLogic({ service: null, id: S3_BATCH_EXPORT.id })
            expect(logic.values.configuration.compression).toBe('gzip')

            logic.actions.setConfigurationValue('file_format', 'JSONLines')
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.configuration.compression).toBe('gzip')

            logic.actions.setConfigurationValue('file_format', 'Parquet')
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.configuration.compression).toBe('gzip')
        })
    })

    describe('invalid persisted compression is dropped on save', () => {
        it('clears a JSONLines+zstd combination when saving an unrelated edit', async () => {
            await initLogic({ service: null, id: S3_BATCH_EXPORT.id })

            logic.actions.setConfigurationValues({
                ...logic.values.configuration,
                file_format: 'JSONLines',
                compression: 'zstd',
                prefix: 'updated-prefix/',
            })

            await expectLogic(logic, () => {
                logic.actions.submitConfiguration()
            }).toDispatchActions(['submitConfiguration', 'updateBatchExportConfigSuccess'])

            expect(lastPatchBody!.destination.config.file_format).toBe('JSONLines')
            expect(lastPatchBody!.destination.config.compression).toBeNull()
            expect(lastPatchBody!.destination.config.prefix).toBe('updated-prefix/')
        })
    })

    describe('Redshift bucket validation only runs in COPY mode', () => {
        // Validates that Redshift's mode-conditional validation only kicks in for COPY mode.
        // INSERT mode shouldn't validate the (irrelevant) bucket name field.
        it.each([
            { mode: 'INSERT', expected: undefined },
            { mode: 'COPY', expected: 'Bucket name must be lowercase' },
        ])('mode=$mode → bucket error: $expected', async ({ mode, expected }) => {
            await initLogic({ service: 'Redshift', id: null })

            logic.actions.setConfigurationValues({
                ...logic.values.configuration,
                user: 'rs-user',
                password: 'rs-pass',
                host: 'rs-host',
                port: 5439,
                database: 'rs-db',
                schema: 'public',
                table_name: 'events',
                mode,
                redshift_s3_bucket: 'INVALID-BUCKET',
                redshift_s3_key_prefix: 'rs/',
                redshift_s3_bucket_region_name: 'us-east-1',
                redshift_iam_role: 'arn:aws:iam::123:role/rs',
                interval: 'hour',
                name: 'Test Export',
                model: 'events',
            })

            logic.actions.submitConfiguration()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.configurationErrors.redshift_s3_bucket).toBe(expected)
        })
    })

    describe('Redshift COPY → INSERT drops the staging copy_inputs', () => {
        // Loading a COPY export flattens copy_inputs into redshift_* form fields. Switching the
        // mode to INSERT must null out copy_inputs (matching a native INSERT export) rather than
        // leaking the original nested staging object back into the payload.
        it('nulls copy_inputs in the saved config when switching to INSERT', async () => {
            await initLogic({ service: null, id: REDSHIFT_COPY_IAM_BATCH_EXPORT.id })

            logic.actions.setConfigurationValues({
                ...logic.values.configuration,
                mode: 'INSERT',
            })

            await expectLogic(logic, () => {
                logic.actions.submitConfiguration()
            })
                .toDispatchActions(['submitConfiguration', 'updateBatchExportConfigSuccess'])
                .toFinishAllListeners()

            const body = patchBodiesById[REDSHIFT_COPY_IAM_BATCH_EXPORT.id]
            expect(body.destination).toEqual({
                type: 'Redshift',
                config: {
                    user: 'rs-user',
                    password: 'rs-pass',
                    host: 'rs-host',
                    port: 5439,
                    database: 'rs-db',
                    schema: 'public',
                    table_name: 'events',
                    properties_data_type: 'SUPER',
                    mode: 'INSERT',
                    copy_inputs: null,
                    exclude_events: [],
                    include_events: [],
                },
            })
        })
    })

    describe('successful update', () => {
        it('sends changed field plus untouched fixture defaults', async () => {
            await initLogic({ service: null, id: S3_BATCH_EXPORT.id })

            logic.actions.setConfigurationValues({
                ...logic.values.configuration,
                prefix: 'updated-prefix/',
            })

            await expectLogic(logic, () => {
                logic.actions.submitConfiguration()
            }).toDispatchActions(['submitConfiguration', 'updateBatchExportConfigSuccess'])

            // Derived from the fixture so default changes don't break this test.
            expect(lastPatchBody!.destination).toEqual({
                type: 'S3',
                config: {
                    ...S3_BATCH_EXPORT.destination.config,
                    prefix: 'updated-prefix/',
                },
            })
        })
    })

    describe('getDefaultConfiguration', () => {
        it.each([
            {
                service: 'S3',
                expected: {
                    destination: 'S3',
                    file_format: 'Parquet',
                    compression: 'zstd',
                    paused: true,
                    model: 'events',
                },
            },
            {
                service: 'AwsS3',
                expected: {
                    destination: 'AwsS3',
                    file_format: 'Parquet',
                    compression: 'zstd',
                    paused: true,
                    model: 'events',
                },
            },
            {
                service: 'S3Compatible',
                expected: {
                    destination: 'S3Compatible',
                    file_format: 'Parquet',
                    compression: 'zstd',
                    paused: true,
                    model: 'events',
                },
            },
            {
                service: 'Snowflake',
                expected: { destination: 'Snowflake', authentication_type: 'password', paused: true, model: 'events' },
            },
            {
                service: 'Redshift',
                expected: {
                    destination: 'Redshift',
                    mode: 'COPY',
                    authorization_mode: 'IAMRole',
                    properties_data_type: 'SUPER',
                    paused: true,
                    model: 'events',
                },
            },
            {
                service: 'Databricks',
                expected: {
                    destination: 'Databricks',
                    use_variant_type: true,
                    http_path: '/sql/1.0/warehouses/',
                    paused: true,
                    model: 'events',
                },
            },
            {
                service: 'AzureBlob',
                expected: {
                    destination: 'AzureBlob',
                    file_format: 'Parquet',
                    compression: 'zstd',
                    paused: true,
                    model: 'events',
                },
            },
            {
                service: 'Postgres',
                expected: { destination: 'Postgres', paused: true, model: 'events' },
            },
            {
                service: 'BigQuery',
                expected: { destination: 'BigQuery', paused: true, model: 'events' },
            },
        ])('returns correct defaults for $service', ({ service, expected }) => {
            const config = getDefaultConfiguration(service)
            expect(config).toEqual(expect.objectContaining(expected))
        })
    })

    // For each destination, fill in only the required fields and assert the exact create payload.
    // Guards against destinations silently changing their default config or required-field set.
    describe('create with required fields per destination', () => {
        it.each([
            {
                name: 'S3',
                service: 'S3' as const,
                requiredValues: {
                    bucket_name: 'my-bucket',
                    region: 'us-east-1',
                    prefix: 'test/',
                    aws_access_key_id: 'AKIA',
                    aws_secret_access_key: 'secret',
                },
                expectedDestination: {
                    type: 'S3',
                    config: {
                        bucket_name: 'my-bucket',
                        region: 'us-east-1',
                        prefix: 'test/',
                        aws_access_key_id: 'AKIA',
                        aws_secret_access_key: 'secret',
                        file_format: 'Parquet',
                        compression: 'zstd',
                    },
                },
            },
            {
                // New AwsS3 exports authenticate via an integration; credentials live on it, and
                // endpoint_url / use_virtual_style_addressing must not leak into the payload.
                name: 'AwsS3',
                service: 'AwsS3' as const,
                requiredValues: {
                    integration_id: 21,
                    bucket_name: 'my-bucket',
                    region: 'us-east-1',
                    prefix: 'test/',
                },
                expectedDestination: {
                    type: 'AwsS3',
                    integration: 21,
                    config: {
                        bucket_name: 'my-bucket',
                        region: 'us-east-1',
                        prefix: 'test/',
                        file_format: 'Parquet',
                        compression: 'zstd',
                    },
                },
            },
            {
                // New S3Compatible exports authenticate via an integration (which carries endpoint_url);
                // no inline credentials, no leaked encryption / kms_key_id.
                name: 'S3Compatible',
                service: 'S3Compatible' as const,
                requiredValues: {
                    integration_id: 22,
                    bucket_name: 'my-bucket',
                    region: 'auto',
                    prefix: 'test/',
                },
                expectedDestination: {
                    type: 'S3Compatible',
                    integration: 22,
                    config: {
                        bucket_name: 'my-bucket',
                        region: 'auto',
                        prefix: 'test/',
                        file_format: 'Parquet',
                        compression: 'zstd',
                    },
                },
            },
            {
                name: 'Postgres',
                service: 'Postgres' as const,
                requiredValues: {
                    integration_id: 13,
                    database: 'pg-db',
                    schema: 'public',
                    table_name: 'events',
                },
                expectedDestination: {
                    type: 'Postgres',
                    integration: 13,
                    config: {
                        database: 'pg-db',
                        schema: 'public',
                        table_name: 'events',
                    },
                },
            },
            {
                name: 'Snowflake (password)',
                service: 'Snowflake' as const,
                requiredValues: {
                    account: 'sf-account',
                    database: 'sf-db',
                    warehouse: 'sf-wh',
                    user: 'sf-user',
                    password: 'sf-pass',
                    schema: 'public',
                    table_name: 'events',
                },
                expectedDestination: {
                    type: 'Snowflake',
                    config: {
                        account: 'sf-account',
                        database: 'sf-db',
                        warehouse: 'sf-wh',
                        user: 'sf-user',
                        password: 'sf-pass',
                        authentication_type: 'password',
                        schema: 'public',
                        table_name: 'events',
                    },
                },
            },
            {
                name: 'Redshift (default COPY + IAM)',
                service: 'Redshift' as const,
                requiredValues: {
                    user: 'rs-user',
                    password: 'rs-pass',
                    host: 'rs-host',
                    port: 5439,
                    database: 'rs-db',
                    schema: 'public',
                    table_name: 'events',
                    redshift_s3_bucket: 'rs-staging',
                    redshift_s3_key_prefix: 'rs/copy/',
                    redshift_s3_bucket_region_name: 'us-east-1',
                    redshift_iam_role: 'arn:aws:iam::123:role/rs',
                },
                expectedDestination: {
                    type: 'Redshift',
                    config: {
                        user: 'rs-user',
                        password: 'rs-pass',
                        host: 'rs-host',
                        port: 5439,
                        database: 'rs-db',
                        schema: 'public',
                        table_name: 'events',
                        properties_data_type: 'SUPER',
                        mode: 'COPY',
                        copy_inputs: {
                            s3_bucket: 'rs-staging',
                            s3_key_prefix: 'rs/copy/',
                            region_name: 'us-east-1',
                            authorization: 'arn:aws:iam::123:role/rs',
                        },
                    },
                },
            },
            {
                name: 'HTTP',
                service: 'HTTP' as const,
                requiredValues: {
                    url: 'https://us.i.posthog.com/batch/',
                    token: 'phc_xxx',
                },
                expectedDestination: {
                    type: 'HTTP',
                    config: {
                        url: 'https://us.i.posthog.com/batch/',
                        token: 'phc_xxx',
                    },
                },
            },
            {
                name: 'Databricks',
                service: 'Databricks' as const,
                requiredValues: {
                    integration_id: 7,
                    http_path: '/sql/1.0/warehouses/abc',
                    catalog: 'workspace',
                    schema: 'default',
                    table_name: 'events',
                },
                expectedDestination: {
                    type: 'Databricks',
                    integration: 7,
                    config: {
                        http_path: '/sql/1.0/warehouses/abc',
                        catalog: 'workspace',
                        schema: 'default',
                        table_name: 'events',
                        use_variant_type: true,
                    },
                },
            },
            {
                name: 'AzureBlob',
                service: 'AzureBlob' as const,
                requiredValues: {
                    integration_id: 11,
                    container_name: 'my-container',
                },
                expectedDestination: {
                    type: 'AzureBlob',
                    integration: 11,
                    config: {
                        container_name: 'my-container',
                        file_format: 'Parquet',
                        compression: 'zstd',
                    },
                },
            },
            {
                name: 'BigQuery',
                service: 'BigQuery' as const,
                requiredValues: {
                    integration_id: 5,
                    dataset_id: 'ds',
                    table_id: 'events',
                },
                expectedDestination: {
                    type: 'BigQuery',
                    integration: 5,
                    config: {
                        dataset_id: 'ds',
                        table_id: 'events',
                    },
                },
            },
        ])('create $name sends expected payload', async ({ service, requiredValues, expectedDestination }) => {
            await initLogic({ service, id: null })

            logic.actions.setConfigurationValues({
                ...logic.values.configuration,
                interval: 'hour',
                name: `Test ${service} Export`,
                model: 'events',
                ...requiredValues,
            })

            await expectLogic(logic, () => {
                logic.actions.submitConfiguration()
            })
                .toDispatchActions(['submitConfiguration', 'updateBatchExportConfigSuccess'])
                .toFinishAllListeners()

            expect(lastPostBody).not.toBeNull()
            expect(lastPostBody!.destination).toEqual(expectedDestination)
            expect(router.values.location.pathname).toContain(urls.batchExport('new-export-id'))
        })
    })

    describe('round-trip: load and save preserves destination config', () => {
        it.each([
            { name: 'S3', fixture: S3_BATCH_EXPORT },
            { name: 'AwsS3', fixture: AWS_S3_BATCH_EXPORT },
            { name: 'S3Compatible', fixture: S3_COMPATIBLE_BATCH_EXPORT },
            { name: 'BigQuery', fixture: BIGQUERY_BATCH_EXPORT },
            { name: 'Postgres', fixture: POSTGRES_BATCH_EXPORT },
            { name: 'Snowflake (password)', fixture: SNOWFLAKE_PASSWORD_BATCH_EXPORT },
            { name: 'Snowflake (keypair)', fixture: SNOWFLAKE_KEYPAIR_BATCH_EXPORT },
            { name: 'Redshift (INSERT)', fixture: REDSHIFT_INSERT_BATCH_EXPORT },
            { name: 'Redshift (COPY + IAM)', fixture: REDSHIFT_COPY_IAM_BATCH_EXPORT },
            { name: 'Redshift (COPY + Credentials)', fixture: REDSHIFT_COPY_CREDENTIALS_BATCH_EXPORT },
            { name: 'HTTP', fixture: HTTP_BATCH_EXPORT },
            { name: 'Databricks', fixture: DATABRICKS_BATCH_EXPORT },
            { name: 'AzureBlob', fixture: AZUREBLOB_BATCH_EXPORT },
        ])('$name round-trips without modifying destination', async ({ fixture }) => {
            await initLogic({ service: null, id: fixture.id })

            // Submit immediately without changes — captures whether deserialize+serialize is symmetrical.
            await expectLogic(logic, () => {
                logic.actions.submitConfiguration()
            })
                .toDispatchActions(['submitConfiguration', 'updateBatchExportConfigSuccess'])
                .toFinishAllListeners()

            const body = patchBodiesById[fixture.id]
            expect(body).not.toBeUndefined()
            expect(body.destination).toEqual(fixture.destination)
        })
    })

    describe('strips stale/legacy config fields not in the destination allowlist', () => {
        // Pre-Integration BigQuery configs can still hold json_config_file + credential fields.
        // Editing such an export must not re-send them, or the backend rejects the PATCH with
        // "Configuration has unknown field/s".
        it('drops pre-Integration BigQuery fields from the PATCH payload', async () => {
            await initLogic({ service: null, id: BIGQUERY_STALE_BATCH_EXPORT.id })

            await expectLogic(logic, () => {
                logic.actions.submitConfiguration()
            })
                .toDispatchActions(['submitConfiguration', 'updateBatchExportConfigSuccess'])
                .toFinishAllListeners()

            const body = patchBodiesById[BIGQUERY_STALE_BATCH_EXPORT.id]
            expect(body).not.toBeUndefined()
            expect(body.destination.config).toEqual({
                dataset_id: 'test_dataset',
                table_id: 'events',
                use_json_type: false,
                exclude_events: [],
                include_events: [],
            })
        })
    })

    describe('grandfathered inline S3 exports stay editable without an integration', () => {
        // AwsS3/S3Compatible are integration-backed for new exports, but exports created before
        // integrations existed have inline credentials and no linked integration. Editing one must not
        // require an integration and must preserve the inline credentials — otherwise the export breaks.
        it('saves an inline AwsS3 export, keeping its credentials and sending no integration', async () => {
            await initLogic({ service: null, id: AWS_S3_BATCH_EXPORT.id })

            logic.actions.setConfigurationValue('prefix', 'updated-prefix/')

            await expectLogic(logic, () => {
                logic.actions.submitConfiguration()
            })
                .toDispatchActions(['submitConfiguration', 'updateBatchExportConfigSuccess'])
                .toFinishAllListeners()

            const body = patchBodiesById[AWS_S3_BATCH_EXPORT.id]
            expect(body).not.toBeUndefined()
            expect(body.destination.integration).toBeUndefined()
            expect(body.destination.config.prefix).toBe('updated-prefix/')
            expect(body.destination.config.aws_access_key_id).toBe('AKIAIOSFODNN7EXAMPLE')
            expect(body.destination.config.aws_secret_access_key).toBe('wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY')
        })
    })
})
