import { router } from 'kea-router'
import { expectLogic, partial } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BatchExportConfiguration } from '~/types'

import {
    BatchExportConfigurationLogicProps,
    batchExportConfigurationLogic,
    getDefaultConfiguration,
} from './batchExportConfigurationLogic'

const MOCK_S3_BATCH_EXPORT: BatchExportConfiguration = {
    id: 'test-s3-id',
    team_id: 997,
    name: 'S3 Export',
    destination: {
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
    },
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

const MOCK_BIGQUERY_BATCH_EXPORT: BatchExportConfiguration = {
    id: 'test-bq-id',
    team_id: 997,
    name: 'BigQuery Export',
    destination: {
        type: 'BigQuery',
        config: {
            project_id: 'test_project',
            private_key: 'test-key',
            private_key_id: 'key-id',
            client_email: 'test@test.iam.gserviceaccount.com',
            token_uri: 'https://oauth2.googleapis.com/token',
            dataset_id: 'test_dataset',
            table_id: 'events',
            exclude_events: [],
            include_events: [],
            use_json_type: false,
        },
    },
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

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: {
        error: jest.fn(),
        success: jest.fn(),
    },
}))

jest.mock('lib/utils/product-intents', () => ({
    addProductIntent: jest.fn().mockResolvedValue(null),
}))

describe('batchExportConfigurationLogic', () => {
    let logic: ReturnType<typeof batchExportConfigurationLogic.build>
    let lastPostBody: Record<string, any> | null = null
    let lastPatchBody: Record<string, any> | null = null

    beforeEach(() => {
        lastPostBody = null
        lastPatchBody = null
        useMocks({
            get: {
                '/api/environments/:team_id/batch_exports/test-s3-id': MOCK_S3_BATCH_EXPORT,
                '/api/environments/:team_id/batch_exports/test-bq-id': MOCK_BIGQUERY_BATCH_EXPORT,
                '/api/environments/:team_id/batch_exports/test': { steps: [] },
            },
            post: {
                '/api/environments/:team_id/batch_exports/': async (req) => {
                    lastPostBody = await req.json()
                    return [200, { ...MOCK_S3_BATCH_EXPORT, id: 'new-export-id' }]
                },
            },
            patch: {
                '/api/environments/:team_id/batch_exports/test-s3-id/': async (req) => {
                    lastPatchBody = await req.json()
                    return [200, MOCK_S3_BATCH_EXPORT]
                },
            },
        })
        initKeaTests()
    })

    async function initLogic(props: BatchExportConfigurationLogicProps): Promise<void> {
        await expectLogic(teamLogic).toFinishAllListeners()
        logic = batchExportConfigurationLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    describe('new batch export config initialization', () => {
        it('sets isNew to true and loads S3 defaults', async () => {
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
        it.each([
            {
                service: 'S3' as const,
                expectedFields: [
                    'interval',
                    'name',
                    'model',
                    'bucket_name',
                    'region',
                    'prefix',
                    'aws_access_key_id',
                    'aws_secret_access_key',
                    'file_format',
                ],
            },
            {
                service: 'Postgres' as const,
                expectedFields: [
                    'interval',
                    'name',
                    'model',
                    'user',
                    'password',
                    'host',
                    'port',
                    'database',
                    'schema',
                    'table_name',
                ],
            },
            {
                service: 'BigQuery' as const,
                expectedFields: ['interval', 'name', 'model', 'json_config_file', 'dataset_id', 'table_id'],
            },
            {
                service: 'Snowflake' as const,
                expectedFields: [
                    'interval',
                    'name',
                    'model',
                    'account',
                    'database',
                    'warehouse',
                    'user',
                    'password',
                    'schema',
                    'table_name',
                ],
            },
            {
                service: 'Redshift' as const,
                expectedFields: [
                    'interval',
                    'name',
                    'model',
                    'user',
                    'password',
                    'host',
                    'port',
                    'database',
                    'schema',
                    'table_name',
                ],
            },
            {
                service: 'HTTP' as const,
                expectedFields: ['interval', 'name', 'model', 'url', 'token'],
            },
            {
                service: 'Databricks' as const,
                expectedFields: [
                    'interval',
                    'name',
                    'model',
                    'integration_id',
                    'http_path',
                    'catalog',
                    'schema',
                    'table_name',
                    'use_variant_type',
                ],
            },
            {
                service: 'AzureBlob' as const,
                expectedFields: ['interval', 'name', 'model', 'integration_id', 'container_name', 'file_format'],
            },
        ])('rejects empty form for $service', async ({ service, expectedFields }) => {
            await initLogic({ service, id: null })

            await expectLogic(logic, () => {
                logic.actions.submitConfiguration()
            }).toDispatchActions(['submitConfiguration', 'submitConfigurationFailure'])

            const errors = logic.values.configurationErrors
            for (const field of expectedFields) {
                expect(errors).toHaveProperty(field)
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
            if (error) {
                expect(errors.bucket_name).toBe(error)
            } else {
                expect(errors.bucket_name).toBeUndefined()
            }
        })
    })

    describe('successful create', () => {
        it('sends correct payload and redirects on success', async () => {
            await initLogic({ service: 'S3', id: null })

            logic.actions.setConfigurationValues({
                ...logic.values.configuration,
                bucket_name: 'my-bucket',
                region: 'us-east-1',
                prefix: 'test/',
                aws_access_key_id: 'AKIAIOSFODNN7EXAMPLE',
                aws_secret_access_key: 'secret',
                file_format: 'Parquet',
                interval: 'hour',
                name: 'Test S3 Export',
                model: 'events',
            })

            await expectLogic(logic, () => {
                logic.actions.submitConfiguration()
            })
                .toDispatchActions(['submitConfiguration', 'updateBatchExportConfigSuccess'])
                .toFinishAllListeners()

            expect(router.values.location.pathname).toContain(urls.batchExport('new-export-id'))
            expect(lastPostBody).toEqual({
                paused: true,
                name: 'Test S3 Export',
                interval: 'hour',
                timezone: null,
                offset_day: null,
                offset_hour: null,
                model: 'events',
                destination: {
                    type: 'S3',
                    config: {
                        file_format: 'Parquet',
                        compression: 'zstd',
                        bucket_name: 'my-bucket',
                        region: 'us-east-1',
                        prefix: 'test/',
                        aws_access_key_id: 'AKIAIOSFODNN7EXAMPLE',
                        aws_secret_access_key: 'secret',
                    },
                },
            })
        })
    })

    describe('successful update', () => {
        it('sends correct payload on existing export', async () => {
            await initLogic({ service: null, id: 'test-s3-id' })

            logic.actions.setConfigurationValues({
                ...logic.values.configuration,
                prefix: 'updated-prefix/',
            })

            await expectLogic(logic, () => {
                logic.actions.submitConfiguration()
            }).toDispatchActions(['submitConfiguration', 'updateBatchExportConfigSuccess'])

            expect(lastPatchBody).toEqual({
                paused: false,
                name: 'S3 Export',
                interval: 'hour',
                timezone: null,
                offset_day: null,
                offset_hour: null,
                model: 'events',
                filters: [],
                destination: {
                    type: 'S3',
                    config: {
                        bucket_name: 'test-bucket',
                        region: 'us-east-1',
                        prefix: 'updated-prefix/',
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
})
