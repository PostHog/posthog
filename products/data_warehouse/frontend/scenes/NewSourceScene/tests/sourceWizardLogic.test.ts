import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { captureMarketingCrossSellClick, getMarketingCrossSellAttribution } from 'lib/marketingCrossSell'

import { ProductIntentContext, ProductKey, WebStatsBreakdown } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import type { AvailableColumn, ExternalDataSource, ExternalDataSourceSyncSchema, IncrementalField } from '~/types'

import {
    externalDataSourcesBulkUpdateSchemasPartialUpdate,
    externalDataSourcesIncrementalFieldRecommendationsCreate,
    externalDataSourcesRetrieve,
} from 'products/warehouse_sources/frontend/generated/api'
import type {
    ExternalDataSourceSerializersApi,
    SourceConfigResponseApi,
} from 'products/warehouse_sources/frontend/generated/api.schemas'

import {
    buildCreateSourcePayload,
    buildKeaFormDefaultFromSourceDetails,
    getDatabaseSchemaPayload,
    getErrorsForFields,
    isPrefixRequired,
    mergeRestoredSourceFormValues,
    resolveConnectErrorMessage,
    shouldHydrateSourceFromUrl,
    sourceWizardLogic,
    WIZARD_DESTINATION_STEP,
} from '../sourceWizardLogic'

jest.mock('products/warehouse_sources/frontend/generated/api', () => ({
    ...jest.requireActual('products/warehouse_sources/frontend/generated/api'),
    externalDataSourcesRetrieve: jest.fn(),
    externalDataSourcesBulkUpdateSchemasPartialUpdate: jest.fn(),
    externalDataSourcesIncrementalFieldRecommendationsCreate: jest.fn(),
}))

type Deferred = {
    resolve: (schemas: ExternalDataSourceSyncSchema[]) => void
    reject: (error: unknown) => void
}

function buildSourceConfig(overrides: Partial<SourceConfigResponseApi>): SourceConfigResponseApi {
    // Fills the fields the wizard endpoint always sends but no case here exercises, so each
    // fixture states only what it is about.
    return {
        name: 'Postgres',
        iconPath: '',
        caption: null,
        fields: [],
        supportsColumnSelection: false,
        versions: [],
        defaultVersion: '',
        deprecatedVersions: [],
        ...overrides,
    }
}

describe('sourceWizardLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it.each<{
        name: SourceConfigResponseApi['name']
        category: SourceConfigResponseApi['category']
        marketingIntent: boolean
    }>([
        { name: 'AdRoll', category: 'Advertising', marketingIntent: true },
        { name: 'AppLovin', category: 'Advertising', marketingIntent: true },
        { name: 'Outbrain', category: 'Advertising', marketingIntent: true },
        { name: 'Taboola', category: 'Advertising', marketingIntent: true },
        { name: 'AmazonAds', category: 'Advertising', marketingIntent: true },
        { name: 'AppleSearchAds', category: 'Advertising', marketingIntent: true },
        { name: 'OpenAIAds', category: 'Advertising', marketingIntent: true },
        { name: 'RoktAds', category: 'Advertising', marketingIntent: true },
        { name: 'MetaAds', category: 'Advertising', marketingIntent: true },
        { name: 'MetaAds', category: null, marketingIntent: false },
        { name: 'BigQuery', category: 'Databases', marketingIntent: false },
        { name: 'Postgres', category: 'Databases', marketingIntent: false },
        { name: 'Hubspot', category: 'CRM', marketingIntent: false },
        { name: 'Mailchimp', category: 'Marketing & email', marketingIntent: false },
    ])('records expected intents for $name ($category)', async ({ name, category, marketingIntent }) => {
        const source = buildSourceConfig({ name, category })
        const updateIntent = jest.spyOn(api.productIntents, 'update').mockResolvedValue(MOCK_DEFAULT_TEAM)
        const logic = sourceWizardLogic({ availableSources: { [name]: source } })
        const unmount = logic.mount()

        try {
            await expectLogic(logic, () => {
                logic.actions.selectConnector(source)
            }).toFinishAllListeners()

            expect(updateIntent.mock.calls.map(([intent]) => intent)).toEqual([
                {
                    product_type: ProductKey.DATA_WAREHOUSE,
                    intent_context: ProductIntentContext.SELECTED_CONNECTOR,
                },
                ...(marketingIntent
                    ? [
                          {
                              product_type: ProductKey.MARKETING_ANALYTICS,
                              intent_context: ProductIntentContext.MARKETING_ANALYTICS_ADS_INTEGRATION_VISITED,
                          },
                      ]
                    : []),
            ])
        } finally {
            unmount()
            updateIntent.mockRestore()
        }
    })

    describe('marketing cross-sell conversions', () => {
        beforeEach(() => {
            sessionStorage.clear()
            jest.spyOn(posthog, 'get_distinct_id').mockReturnValue('test-user')
            jest.spyOn(posthog, 'capture').mockClear()
            jest.spyOn(api.productIntents, 'update').mockResolvedValue(MOCK_DEFAULT_TEAM)
            featureFlagLogic.mount()
        })
        afterEach(() => {
            sessionStorage.clear()
            jest.restoreAllMocks()
        })

        it.each([
            { enabled: true, category: 'Advertising', attributed: true },
            { enabled: false, category: 'Advertising', attributed: false },
            { enabled: true, category: 'Databases', attributed: false },
            { enabled: true, category: 'Marketing & email', attributed: false },
        ] as const)(
            'attributes success only for eligible sources: $enabled / $category',
            async ({ enabled, category, attributed }) => {
                featureFlagLogic.actions.setFeatureFlags([], {
                    [FEATURE_FLAGS.WEB_ANALYTICS_MARKETING_CROSS_SELL]: enabled,
                })
                const source = buildSourceConfig({
                    name:
                        category === 'Advertising'
                            ? 'GoogleAds'
                            : category === 'Marketing & email'
                              ? 'GoogleSearchConsole'
                              : 'Postgres',
                    category,
                })
                const logic = sourceWizardLogic({
                    availableSources: { [source.name]: source },
                    onComplete: jest.fn(),
                    requiredTables: [],
                })
                const unmount = logic.mount()
                jest.spyOn(api.externalDataSources, 'create').mockResolvedValue({ id: 'test-ad-source' } as Awaited<
                    ReturnType<typeof api.externalDataSources.create>
                >)
                try {
                    await expectLogic(logic, () => logic.actions.selectConnector(source)).toFinishAllListeners()
                    captureMarketingCrossSellClick(MOCK_DEFAULT_TEAM.id, WebStatsBreakdown.InitialChannelType, false)
                    const attribution = getMarketingCrossSellAttribution(MOCK_DEFAULT_TEAM.id)!
                    if (category !== 'Databases') {
                        logic.actions.setReturnConfig(
                            '/project/997/marketing?tab=ad-performance',
                            'Marketing analytics',
                            'marketing_analytics_mcp'
                        )
                    }
                    await expectLogic(logic, () => logic.actions.createSource()).toFinishAllListeners()
                    expect(posthog.capture).toHaveBeenCalledWith(
                        'warehouse source connect completed',
                        expect.objectContaining({
                            sourceType: source.name,
                            returnLabel: category === 'Databases' ? undefined : 'Marketing analytics',
                            entry_point: category === 'Databases' ? undefined : 'marketing_analytics_mcp',
                        })
                    )
                    const conversions = jest
                        .mocked(posthog.capture)
                        .mock.calls.filter(([name]) => name === 'web analytics marketing cross sell source created')
                    expect(conversions).toEqual(
                        attributed
                            ? [
                                  [
                                      'web analytics marketing cross sell source created',
                                      expect.objectContaining({
                                          cross_sell_id: attribution.cross_sell_id,
                                          source_id: 'test-ad-source',
                                          source_type: 'GoogleAds',
                                      }),
                                  ],
                              ]
                            : []
                    )
                } finally {
                    unmount()
                }
            }
        )

        it('retains attribution after failure and records conversion after a successful retry', async () => {
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WEB_ANALYTICS_MARKETING_CROSS_SELL]: true })
            const source = buildSourceConfig({ name: 'GoogleAds', category: 'Advertising' })
            const logic = sourceWizardLogic({
                availableSources: { GoogleAds: source },
                onComplete: jest.fn(),
                requiredTables: [],
            })
            const unmount = logic.mount()
            jest.spyOn(api.externalDataSources, 'create')
                .mockRejectedValueOnce({ status: 400, message: 'Invalid credentials' })
                .mockResolvedValueOnce({ id: 'test-ad-source' } as Awaited<
                    ReturnType<typeof api.externalDataSources.create>
                >)
            try {
                await expectLogic(logic, () => logic.actions.selectConnector(source)).toFinishAllListeners()
                captureMarketingCrossSellClick(MOCK_DEFAULT_TEAM.id, WebStatsBreakdown.InitialUTMCampaign, false)
                const attribution = getMarketingCrossSellAttribution(MOCK_DEFAULT_TEAM.id)!
                await expectLogic(logic, () => logic.actions.createSource()).toFinishAllListeners()
                expect(posthog.capture).not.toHaveBeenCalledWith(
                    'warehouse source connect completed',
                    expect.anything()
                )
                expect(posthog.capture).not.toHaveBeenCalledWith(
                    'web analytics marketing cross sell source created',
                    expect.anything()
                )
                expect(getMarketingCrossSellAttribution(MOCK_DEFAULT_TEAM.id)).toEqual(attribution)
                await expectLogic(logic, () => logic.actions.createSource()).toFinishAllListeners()
                expect(posthog.capture).toHaveBeenCalledWith(
                    'web analytics marketing cross sell source created',
                    expect.objectContaining({
                        cross_sell_id: attribution.cross_sell_id,
                        source_id: 'test-ad-source',
                    })
                )
                expect(getMarketingCrossSellAttribution(MOCK_DEFAULT_TEAM.id)).toBeNull()
            } finally {
                unmount()
            }
        })
    })

    it('shares a single wizard instance across references with the same props', () => {
        const postgresSource = buildSourceConfig({ name: 'Postgres' })
        const availableSources = { Postgres: postgresSource }
        const firstReference = sourceWizardLogic({ availableSources })
        const secondReference = sourceWizardLogic({ availableSources })
        const unmount = firstReference.mount()

        try {
            firstReference.actions.selectConnector(postgresSource)
            firstReference.actions.setStep(2)
            firstReference.actions.setSourceConnectionDetailsValue(['payload', 'host'], 'shared.example.com')

            expect(secondReference.values.selectedConnector?.name).toEqual('Postgres')
            expect(secondReference.values.currentStep).toEqual(2)
            expect(secondReference.values.sourceConnectionDetails.payload.host).toEqual('shared.example.com')
        } finally {
            unmount()
        }
    })

    it('advances from the webhook step to the progress step without also completing the wizard', () => {
        // Regression test: onSubmit used to read `values.currentStep` again after onNext()
        // advanced it, so a single click on step 4 (webhook) fell through into the step-5
        // completion branch in the same call, skipping the progress step entirely.
        const postgresSource = buildSourceConfig({ name: 'Postgres' })
        const onComplete = jest.fn()
        const logic = sourceWizardLogic({ availableSources: { Postgres: postgresSource }, onComplete })
        const unmount = logic.mount()

        try {
            logic.actions.selectConnector(postgresSource)
            logic.actions.setStep(4)
            logic.actions.setWebhookResult({ success: true, webhook_url: 'https://example.com/webhook' })

            logic.actions.onSubmit()

            expect(logic.values.currentStep).toEqual(5)
            expect(onComplete).not.toHaveBeenCalled()
        } finally {
            unmount()
        }
    })

    describe('webhook step', () => {
        const stripeWithSecret = buildSourceConfig({
            name: 'Stripe',
            webhookFields: [{ name: 'signing_secret', label: 'Signing secret', type: 'password', required: true }],
        } as Partial<SourceConfigResponseApi>)
        const stripeWithoutFields = buildSourceConfig({ name: 'Stripe' })

        it.each([
            ['auto setup finished', stripeWithSecret, { success: true, webhook_url: 'u' }, false, true],
            [
                'a secret is still pending',
                stripeWithSecret,
                { success: true, webhook_url: 'u', pending_inputs: ['signing_secret'] },
                true,
                false,
            ],
            [
                'manual setup with a required field to save',
                stripeWithSecret,
                { success: false, webhook_url: 'u', error: 'e' },
                true,
                false,
            ],
            [
                'manual setup not confirmed',
                stripeWithoutFields,
                { success: false, webhook_url: 'u', error: 'e' },
                false,
                false,
            ],
            [
                'manual setup confirmed',
                stripeWithoutFields,
                { success: false, webhook_url: 'u', error: 'e' },
                true,
                true,
            ],
            [
                'request failed with no URL',
                stripeWithoutFields,
                { success: false, webhook_url: '', error: 'e' },
                true,
                false,
            ],
        ])('blocks Next unless the webhook works: %s', (_name, connector, result, confirmed, expected) => {
            const logic = sourceWizardLogic({ availableSources: { Stripe: connector } })
            const unmount = logic.mount()

            try {
                logic.actions.selectConnector(connector)
                logic.actions.setStep(4)
                logic.actions.setWebhookResult(result)
                logic.actions.setWebhookManualSetupConfirmed(confirmed)

                expect(logic.values.webhookStepComplete).toBe(expected)
                expect(logic.values.canGoNext).toBe(expected)
            } finally {
                unmount()
            }
        })

        it('switches only the syncing, pollable webhook tables to a polling sync method', async () => {
            const schema = (overrides: Partial<ExternalDataSourceSyncSchema>): ExternalDataSourceSyncSchema =>
                ({
                    table: 'Customer',
                    label: null,
                    should_sync: true,
                    sync_type: 'webhook',
                    incremental_field: null,
                    incremental_field_type: null,
                    incremental_fields: [],
                    incremental_available: false,
                    append_available: false,
                    supports_webhooks: true,
                    available_columns: [],
                    ...overrides,
                }) as ExternalDataSourceSyncSchema
            jest.mocked(externalDataSourcesRetrieve).mockResolvedValue({
                schemas: [
                    { id: 's1', name: 'Customer', sync_type: 'webhook', should_sync: true },
                    { id: 's2', name: 'Invoice', sync_type: 'webhook', should_sync: true },
                    { id: 's3', name: 'Charge', sync_type: 'incremental', should_sync: true },
                    { id: 's4', name: 'Payout', sync_type: 'webhook', should_sync: false },
                    { id: 's5', name: 'Discount', sync_type: 'webhook', should_sync: true },
                ],
            } as unknown as ExternalDataSourceSerializersApi)
            const bulkUpdate = jest.mocked(externalDataSourcesBulkUpdateSchemasPartialUpdate).mockResolvedValue([])
            const logic = sourceWizardLogic({ availableSources: { Stripe: stripeWithSecret } })
            const unmount = logic.mount()

            try {
                logic.actions.selectConnector(stripeWithSecret)
                logic.actions.setDatabaseSchemas([
                    schema({
                        table: 'Customer',
                        incremental_available: true,
                        incremental_fields: [
                            { label: 'created', type: 'datetime', field: 'created', field_type: 'integer' },
                        ] as IncrementalField[],
                    }),
                    schema({ table: 'Invoice' }),
                    schema({ table: 'Charge', sync_type: 'incremental' }),
                    schema({ table: 'Payout', should_sync: false }),
                    schema({ table: 'Discount', webhook_only: true }),
                ])
                logic.actions.setSourceId('source-1')
                logic.actions.setStep(4)

                await expectLogic(logic, () => logic.actions.switchWebhookTablesToPolling()).toFinishAllListeners()

                expect(bulkUpdate).toHaveBeenCalledWith(expect.any(String), 'source-1', {
                    schemas: [
                        {
                            id: 's1',
                            sync_type: 'incremental',
                            incremental_field: 'created',
                            incremental_field_type: 'integer',
                        },
                        { id: 's2', sync_type: 'full_refresh', incremental_field: null, incremental_field_type: null },
                    ],
                })
                expect(logic.values.databaseSchema.find((s) => s.table === 'Discount')?.sync_type).toBe('webhook')
                expect(logic.values.currentStep).toBe(5)
            } finally {
                unmount()
            }
        })
    })

    it('does not hydrate the same source URL again after the wizard has started', () => {
        const postgresSource = buildSourceConfig({ name: 'Postgres' })

        expect(shouldHydrateSourceFromUrl(2, postgresSource, postgresSource, 'direct', 'direct')).toBe(false)
        expect(shouldHydrateSourceFromUrl(1, postgresSource, postgresSource, 'direct', 'direct')).toBe(true)
        expect(shouldHydrateSourceFromUrl(2, postgresSource, postgresSource, 'warehouse', 'direct')).toBe(true)
    })

    describe('isPrefixRequired', () => {
        const source = (source_type: string, prefix: string | null): ExternalDataSource =>
            ({ source_type, prefix }) as ExternalDataSource

        test.each([
            ['no sources yet', [], false],
            ['an unprefixed source of the same type', [source('Stripe', null)], true],
            ['an empty-string prefix on the same type', [source('Stripe', '')], true],
            ['only prefixed sources of the same type', [source('Stripe', 'eu')], false],
            ['an unprefixed source of another type', [source('Hubspot', null)], false],
        ])('with %s', (_, sources, expected) => {
            expect(isPrefixRequired(sources, 'Stripe')).toBe(expected)
        })
    })

    describe('resolveConnectErrorMessage', () => {
        it('guides toward ad blockers when a request never reaches the server', () => {
            // A thrown fetch has no HTTP status; without this branch the user only sees "Failed to fetch".
            const message = resolveConnectErrorMessage({ message: 'Failed to fetch', status: undefined })
            expect(message).toContain('ad blocker')
            expect(message).not.toEqual('Failed to fetch')
        })

        it('prefers an API-provided message over the network hint', () => {
            expect(resolveConnectErrorMessage({ data: { message: 'Invalid credentials' }, status: 400 })).toEqual(
                'Invalid credentials'
            )
        })

        it('replaces the generic server-error detail with connection guidance', () => {
            // DRF answers an unhandled 500 with a fixed placeholder detail. Surfacing it told the
            // user nothing, and it masked the 5xx branch below.
            const message = resolveConnectErrorMessage({ detail: 'A server error occurred.', status: 500 })
            expect(message).toContain('the details you entered')
            expect(message).not.toContain('A server error occurred.')
        })

        it('keeps the 5xx guidance free of causes only database sources have', () => {
            // Every source shares this branch, so wording aimed at a database sent users of
            // API-backed sources looking for a schema and a host they never configured.
            const message = resolveConnectErrorMessage({ status: 504 })
            expect(message).not.toMatch(/database|schema/i)
        })

        it('never returns undefined for a 4xx with no message body', () => {
            const message = resolveConnectErrorMessage({ status: 400 })
            expect(message).toBeTruthy()
            expect(message).not.toEqual('undefined')
        })
    })

    describe('buildCreateSourcePayload', () => {
        beforeEach(() => {
            featureFlagLogic.mount()
        })

        it.each([
            { connector: 'Postgres', flagOn: false, expectedAccessMethod: 'direct' },
            { connector: 'BigQuery', flagOn: false, expectedAccessMethod: 'warehouse' },
            { connector: 'BigQuery', flagOn: true, expectedAccessMethod: 'direct' },
        ])(
            'keeps direct mode for $connector only when supported (flag on: $flagOn)',
            ({ connector, flagOn, expectedAccessMethod }) => {
                featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.BIGQUERY_DIRECT_QUERY]: flagOn })

                const payload = buildCreateSourcePayload({ access_method: 'direct', prefix: 'bq' } as any, connector)

                expect(payload).toMatchObject({ access_method: expectedAccessMethod, source_type: connector })
            }
        )
    })

    describe('getDatabaseSchemaPayload', () => {
        it('includes the selected access method for schema discovery', () => {
            expect(
                getDatabaseSchemaPayload({
                    access_method: 'direct',
                    payload: {
                        host: 'localhost',
                        schema: '',
                    },
                })
            ).toEqual({
                access_method: 'direct',
                host: 'localhost',
                schema: '',
            })
        })

        it('defaults to warehouse mode', () => {
            expect(
                getDatabaseSchemaPayload({
                    payload: {
                        host: 'localhost',
                    },
                })
            ).toEqual({
                access_method: 'warehouse',
                host: 'localhost',
            })
        })
    })

    describe('buildKeaFormDefaultFromSourceDetails', () => {
        it('returns the default for an empty source', async () => {
            const res = buildKeaFormDefaultFromSourceDetails({})

            expect(res).toEqual({ prefix: '', description: '', payload: {} })
        })

        it('returns defaults for text fields', async () => {
            const sourceWizardLogic = await import('../sourceWizardLogic')
            const res = sourceWizardLogic.buildKeaFormDefaultFromSourceDetails({
                Test: buildSourceConfig({
                    name: 'Stripe',
                    fields: [
                        {
                            name: 'test_field',
                            label: 'Test',
                            type: 'text',
                            required: true,
                            placeholder: 'Enter something',
                            secret: false,
                        },
                    ],
                }),
            })

            expect(res).toEqual({ prefix: '', description: '', payload: { test_field: '' } })
        })

        it('returns defaults for pure select field', async () => {
            const sourceWizardLogic = await import('../sourceWizardLogic')
            const res = sourceWizardLogic.buildKeaFormDefaultFromSourceDetails({
                Test: buildSourceConfig({
                    name: 'Stripe',
                    fields: [
                        {
                            name: 'test_field',
                            label: 'Test',
                            type: 'select',
                            required: true,
                            options: [{ value: 'value1', label: 'label' }],
                            defaultValue: 'value1',
                        },
                    ],
                }),
            })

            expect(res).toEqual({ prefix: '', description: '', payload: { test_field: 'value1' } })
        })

        it('returns an array default for a multiple select field', async () => {
            const sourceWizardLogic = await import('../sourceWizardLogic')
            const res = sourceWizardLogic.buildKeaFormDefaultFromSourceDetails({
                Test: buildSourceConfig({
                    name: 'GoogleSearchConsole',
                    fields: [
                        {
                            name: 'search_types',
                            label: 'Search types',
                            type: 'select',
                            required: true,
                            multiple: true,
                            options: [
                                { value: 'web', label: 'Web' },
                                { value: 'image', label: 'Image' },
                            ],
                            defaultValue: 'web',
                        },
                    ],
                }),
            })

            expect(res).toEqual({ prefix: '', description: '', payload: { search_types: ['web'] } })
        })

        it('returns defaults for select field with fields', async () => {
            const sourceWizardLogic = await import('../sourceWizardLogic')
            const res = sourceWizardLogic.buildKeaFormDefaultFromSourceDetails({
                Test: buildSourceConfig({
                    name: 'Stripe',
                    fields: [
                        {
                            name: 'test_field',
                            label: 'Test',
                            type: 'select',
                            required: true,
                            options: [
                                {
                                    value: 'value1',
                                    label: 'label',
                                    fields: [
                                        {
                                            name: 'option_field',
                                            label: 'Test',
                                            type: 'text',
                                            required: true,
                                            placeholder: 'Enter something',
                                            secret: false,
                                        },
                                    ],
                                },
                            ],
                            defaultValue: 'value1',
                        },
                    ],
                }),
            })

            expect(res).toEqual({
                prefix: '',
                description: '',
                payload: { test_field: { selection: 'value1', option_field: '' } },
            })
        })

        it('returns defaults for switch group field - default disabled', async () => {
            const sourceWizardLogic = await import('../sourceWizardLogic')
            const res = sourceWizardLogic.buildKeaFormDefaultFromSourceDetails({
                Test: buildSourceConfig({
                    name: 'Stripe',
                    fields: [
                        {
                            name: 'test_field',
                            label: 'Test',
                            type: 'switch-group',
                            default: false,
                            fields: [
                                {
                                    name: 'option_field',
                                    label: 'Test',
                                    type: 'text',
                                    required: true,
                                    placeholder: 'Enter something',
                                    secret: false,
                                },
                            ],
                        },
                    ],
                }),
            })

            expect(res).toEqual({
                prefix: '',
                description: '',
                payload: { test_field: { enabled: false, option_field: '' } },
            })
        })

        it('returns defaults for switch group field - default enabled', async () => {
            const sourceWizardLogic = await import('../sourceWizardLogic')
            const res = sourceWizardLogic.buildKeaFormDefaultFromSourceDetails({
                Test: buildSourceConfig({
                    name: 'Stripe',
                    fields: [
                        {
                            name: 'test_field',
                            label: 'Test',
                            type: 'switch-group',
                            default: true,
                            fields: [
                                {
                                    name: 'option_field',
                                    label: 'Test',
                                    type: 'text',
                                    required: true,
                                    placeholder: 'Enter something',
                                    secret: false,
                                },
                            ],
                        },
                    ],
                }),
            })

            expect(res).toEqual({
                prefix: '',
                description: '',
                payload: { test_field: { enabled: true, option_field: '' } },
            })
        })
    })

    describe('getErrorsForFields', () => {
        it('returns no errors for an empty payload', () => {
            const res = getErrorsForFields([], { prefix: '', payload: {} })
            expect(res).toEqual({ payload: {} })
        })

        // Warehouse-mode prefixes must satisfy the backend `validate_source_prefix` rules so an
        // invalid prefix is caught in the wizard rather than only after the create request fails.
        it.each([
            ['@@@', true],
            ['my-prefix', true], // hyphen — rejected by the backend, previously allowed here
            ['2things', true], // leading digit
            ['___', true], // only underscores
            [' my ', true], // backend strips only underscores, not whitespace
            ['my_prefix', false],
            ['_leading', false],
            ['', false], // empty prefix is allowed
        ])('validates warehouse-mode prefix %p', (prefix, expectError) => {
            const res = getErrorsForFields([], { prefix, payload: {} })
            if (expectError) {
                expect(res.prefix).toBeTruthy()
            } else {
                expect(res.prefix).toBeUndefined()
            }
        })

        it('requires name for direct mode', () => {
            const res = getErrorsForFields([], { prefix: '   ', payload: {}, access_method: 'direct' })
            expect(res.prefix).toEqual('Please enter a name for this direct query source.')
        })

        it('allows non-prefix characters for direct mode name', () => {
            const res = getErrorsForFields([], {
                prefix: 'prod us-east (readonly)',
                payload: {},
                access_method: 'direct',
            })
            expect(res.prefix).toBeUndefined()
        })

        it('returns errors for an empty required text field', () => {
            const res = getErrorsForFields(
                [
                    {
                        name: 'test_field',
                        label: 'Test',
                        type: 'text',
                        required: true,
                        placeholder: 'Enter something',
                        secret: false,
                    },
                ],
                { prefix: '', payload: {} }
            )
            expect(res.payload.test_field).toBeTruthy()
        })

        it('returns an error for a required multiple select with nothing selected', () => {
            // An empty array is truthy, so without an array-aware check the form submits
            // with no selection and the source syncs nothing.
            const res = getErrorsForFields(
                [
                    {
                        name: 'search_types',
                        label: 'Search types',
                        type: 'select',
                        required: true,
                        multiple: true,
                        options: [
                            { value: 'web', label: 'Web' },
                            { value: 'image', label: 'Image' },
                        ],
                        defaultValue: 'web',
                    },
                ],
                { prefix: '', payload: { search_types: [] } }
            )
            expect(res.payload.search_types).toBeTruthy()
        })

        it('returns no errors for a required multiple select with a selection', () => {
            const res = getErrorsForFields(
                [
                    {
                        name: 'search_types',
                        label: 'Search types',
                        type: 'select',
                        required: true,
                        multiple: true,
                        options: [
                            { value: 'web', label: 'Web' },
                            { value: 'image', label: 'Image' },
                        ],
                        defaultValue: 'web',
                    },
                ],
                { prefix: '', payload: { search_types: ['image'] } }
            )
            expect(res.payload).toEqual({})
        })

        it('returns no errors for an empty non-required text field', () => {
            const res = getErrorsForFields(
                [
                    {
                        name: 'test_field',
                        label: 'Test',
                        type: 'text',
                        required: false,
                        placeholder: 'Enter something',
                        secret: false,
                    },
                ],
                { prefix: '', payload: {} }
            )
            expect(res.payload).toEqual({})
        })

        it('returns errors for an empty required select field', () => {
            const res = getErrorsForFields(
                [
                    {
                        name: 'test_field',
                        label: 'Test',
                        type: 'select',
                        required: true,
                        options: [{ value: 'value', label: 'label' }],
                        defaultValue: 'value',
                    },
                ],
                { prefix: '', payload: {} }
            )
            expect(res.payload.test_field).toBeTruthy()
        })

        it('returns no errors for an empty non-required select field', () => {
            const res = getErrorsForFields(
                [
                    {
                        name: 'test_field',
                        label: 'Test',
                        type: 'select',
                        required: false,
                        options: [{ value: 'value', label: 'label' }],
                        defaultValue: 'value',
                    },
                ],
                { prefix: '', payload: {} }
            )
            expect(res.payload).toEqual({})
        })

        it('returns errors for empty children fields of select field', () => {
            const res = getErrorsForFields(
                [
                    {
                        name: 'test_field',
                        label: 'Test',
                        type: 'select',
                        required: true,
                        options: [
                            {
                                value: 'value',
                                label: 'label',
                                fields: [
                                    {
                                        name: 'option_field',
                                        label: 'Test',
                                        type: 'text',
                                        required: true,
                                        placeholder: 'Enter something',
                                        secret: false,
                                    },
                                ],
                            },
                        ],
                        defaultValue: 'value',
                    },
                ],
                { prefix: '', payload: { test_field: { selection: 'value', option_field: '' } } }
            )
            expect(res.payload.test_field.option_field).toBeTruthy()
        })

        it('returns no errors for empty children fields of select field that arent selected', () => {
            const res = getErrorsForFields(
                [
                    {
                        name: 'test_field',
                        label: 'Test',
                        type: 'select',
                        required: true,
                        options: [
                            {
                                value: 'value',
                                label: 'label',
                                fields: [
                                    {
                                        name: 'option_field',
                                        label: 'Test',
                                        type: 'text',
                                        required: true,
                                        placeholder: 'Enter something',
                                        secret: false,
                                    },
                                ],
                            },
                            {
                                value: 'other_value',
                                label: 'label',
                                fields: [
                                    {
                                        name: 'non_selected_value',
                                        label: 'Test',
                                        type: 'text',
                                        required: true,
                                        placeholder: 'Enter something',
                                        secret: false,
                                    },
                                ],
                            },
                        ],
                        defaultValue: 'value',
                    },
                ],
                {
                    prefix: '',
                    payload: { test_field: { selection: 'value', option_field: 'hello', non_selected_value: '' } },
                }
            )
            expect(res.payload.test_field.option_field).toBeUndefined()
            expect(res.payload.test_field.non_selected_value).toBeUndefined()
        })

        it('returns no errors for an empty non-required text field within a switch group field', () => {
            const res = getErrorsForFields(
                [
                    {
                        name: 'test_field',
                        label: 'Test',
                        type: 'switch-group',
                        default: false,
                        fields: [
                            {
                                name: 'option_field',
                                label: 'Test',
                                type: 'text',
                                required: false,
                                placeholder: 'Enter something',
                                secret: false,
                            },
                        ],
                    },
                ],
                { prefix: '', payload: { test_field: { enabled: true, option_field: '' } } }
            )
            expect(res.payload.test_field).toEqual({})
        })

        it('returns no errors for an empty required text field within a disabled switch group field', () => {
            const res = getErrorsForFields(
                [
                    {
                        name: 'test_field',
                        label: 'Test',
                        type: 'switch-group',
                        default: false,
                        fields: [
                            {
                                name: 'option_field',
                                label: 'Test',
                                type: 'text',
                                required: true,
                                placeholder: 'Enter something',
                                secret: false,
                            },
                        ],
                    },
                ],
                { prefix: '', payload: { test_field: { enabled: false, option_field: '' } } }
            )
            expect(res.payload).toEqual({})
        })

        it('returns no errors for a filled required text field within a switch group field', () => {
            const res = getErrorsForFields(
                [
                    {
                        name: 'test_field',
                        label: 'Test',
                        type: 'switch-group',
                        default: false,
                        fields: [
                            {
                                name: 'option_field',
                                label: 'Test',
                                type: 'text',
                                required: true,
                                placeholder: 'Enter something',
                                secret: false,
                            },
                        ],
                    },
                ],
                { prefix: '', payload: { test_field: { enabled: true, option_field: 'some_value' } } }
            )
            expect(res.payload.test_field).toEqual({})
        })

        it('returns errors for an empty required text field within a switch group field', () => {
            const res = getErrorsForFields(
                [
                    {
                        name: 'test_field',
                        label: 'Test',
                        type: 'switch-group',
                        default: false,
                        fields: [
                            {
                                name: 'option_field',
                                label: 'Test',
                                type: 'text',
                                required: true,
                                placeholder: 'Enter something',
                                secret: false,
                            },
                        ],
                    },
                ],
                { prefix: '', payload: { test_field: { enabled: true, option_field: '' } } }
            )
            expect(res.payload.test_field.option_field).toBeTruthy()
        })

        it('allows empty password in edit mode validation', () => {
            const res = getErrorsForFields(
                [
                    {
                        name: 'password',
                        label: 'Password',
                        type: 'password',
                        required: true,
                        placeholder: '',
                        secret: true,
                    },
                ],
                { prefix: 'prod-db', payload: { password: '' }, access_method: 'direct' },
                { allowBlankSensitiveFields: true }
            )
            expect(res.payload.password).toBeUndefined()
        })

        it('allows empty secret-marked textarea in edit mode validation', () => {
            // Regression: a multi-line credential field uses type: 'textarea' for UX
            // but is still a secret. The validator must allow blank values for any
            // field with secret: true regardless of its rendering type.
            const res = getErrorsForFields(
                [
                    {
                        name: 'client_private_key',
                        label: 'Client private key',
                        type: 'textarea',
                        required: true,
                        placeholder: '',
                        secret: true,
                    },
                ],
                { prefix: 'temporal-source', payload: { client_private_key: '' }, access_method: 'direct' },
                { allowBlankSensitiveFields: true }
            )
            expect(res.payload.client_private_key).toBeUndefined()
        })

        it('still flags blank required non-secret fields in edit mode', () => {
            // Sanity check: the secret blank-allow exception must not also let blank
            // required non-secret fields through.
            const res = getErrorsForFields(
                [
                    {
                        name: 'host',
                        label: 'Host',
                        type: 'text',
                        required: true,
                        placeholder: '',
                        secret: false,
                    },
                ],
                { prefix: 'src', payload: { host: '' }, access_method: 'direct' },
                { allowBlankSensitiveFields: true }
            )
            expect(res.payload.host).toBe('Host is required')
        })
    })

    describe('mergeRestoredSourceFormValues', () => {
        const defaults = { prefix: '', description: '', payload: { using_ssl: 'true' } }

        it('uses the URL access_method when there are no saved values', () => {
            expect(mergeRestoredSourceFormValues(defaults, null, 'direct')).toEqual({
                prefix: '',
                description: '',
                payload: { using_ssl: 'true' },
                access_method: 'direct',
            })
        })

        it('keeps the saved access_method when one exists', () => {
            // OAuth callback URL doesn't carry access_method forward — saved value must win.
            const saved = { access_method: 'warehouse', payload: { host: 'localhost' } }
            expect(mergeRestoredSourceFormValues(defaults, saved, 'direct')).toEqual({
                prefix: '',
                description: '',
                payload: { host: 'localhost' },
                access_method: 'warehouse',
            })
        })

        it('omits access_method when neither saved values nor current state provide one', () => {
            expect(mergeRestoredSourceFormValues(defaults, null, undefined)).toEqual(defaults)
        })

        it('overlays saved values on top of connector schema defaults', () => {
            const saved = { payload: { host: 'foo' } }
            // saved.payload replaces defaults.payload wholesale (shallow merge)
            expect(mergeRestoredSourceFormValues(defaults, saved, 'warehouse')).toEqual({
                prefix: '',
                description: '',
                payload: { host: 'foo' },
                access_method: 'warehouse',
            })
        })
    })

    // Reducer guards for permission_error rows (Stripe scope gating).
    describe('permission_error sync gating', () => {
        const stripeSource = buildSourceConfig({ name: 'Stripe' })

        const buildSchema = (overrides: Partial<ExternalDataSourceSyncSchema> = {}): ExternalDataSourceSyncSchema =>
            ({
                table: 'Customer',
                label: null,
                rows: null,
                should_sync: false,
                sync_time_of_day: null,
                incremental_field: null,
                incremental_field_type: null,
                sync_type: null,
                incremental_fields: [],
                incremental_available: false,
                append_available: false,
                supports_webhooks: true,
                description: null,
                should_sync_default: true,
                primary_key_columns: null,
                available_columns: [],
                detected_primary_keys: null,
                permission_error: null,
                ...overrides,
            }) as ExternalDataSourceSyncSchema

        const mountWithSchemas = (
            schemas: ExternalDataSourceSyncSchema[]
        ): { logic: ReturnType<typeof sourceWizardLogic>; unmount: () => void } => {
            const logic = sourceWizardLogic({
                availableSources: { Stripe: stripeSource },
            })
            const unmount = logic.mount()
            logic.actions.selectConnector(stripeSource)
            logic.actions.setDatabaseSchemas(schemas)
            return { logic, unmount }
        }

        it('toggleAllTables(selectAll=true) leaves permission_error rows unchecked', () => {
            const { logic, unmount } = mountWithSchemas([
                buildSchema({ table: 'Customer' }),
                buildSchema({ table: 'Charge', permission_error: 'Missing rak_charge_read' }),
            ])

            try {
                logic.actions.toggleAllTables(true)
                const byTable = Object.fromEntries(logic.values.databaseSchema.map((s) => [s.table, s]))
                expect(byTable['Customer'].should_sync).toBe(true)
                expect(byTable['Charge'].should_sync).toBe(false)
            } finally {
                unmount()
            }
        })

        it('toggleAllTables(selectAll=true) never opts into default-off rows, deselect still clears them', () => {
            // Default-off tables (e.g. Supabase Vault secrets tables) need an explicit per-table
            // opt-in; select-all must neither enable them nor undo a deliberate manual opt-in.
            const { logic, unmount } = mountWithSchemas([
                buildSchema({ table: 'Customer' }),
                buildSchema({ table: 'vault.decrypted_secrets', should_sync_default: false }),
                buildSchema({ table: 'vault.secrets', should_sync_default: false, should_sync: true }),
            ])
            const toastInfo = jest.spyOn(lemonToast, 'info').mockImplementation(() => ({ id: 'x' }) as any)

            try {
                logic.actions.toggleAllTables(true)
                let byTable = Object.fromEntries(logic.values.databaseSchema.map((s) => [s.table, s]))
                expect(byTable['Customer'].should_sync).toBe(true)
                expect(byTable['vault.decrypted_secrets'].should_sync).toBe(false)
                expect(byTable['vault.secrets'].should_sync).toBe(true)
                expect(toastInfo).toHaveBeenCalledWith(expect.stringContaining('off by default'))

                toastInfo.mockClear()
                logic.actions.toggleAllTables(false)
                byTable = Object.fromEntries(logic.values.databaseSchema.map((s) => [s.table, s]))
                expect(byTable['vault.secrets'].should_sync).toBe(false)
                expect(toastInfo).not.toHaveBeenCalled()
            } finally {
                toastInfo.mockRestore()
                unmount()
            }
        })

        it('toggleAllTables(selectAll=true) with explicit tableNames still skips permission_error rows', () => {
            const { logic, unmount } = mountWithSchemas([
                buildSchema({ table: 'Customer' }),
                buildSchema({ table: 'Charge', permission_error: 'Missing rak_charge_read' }),
            ])

            try {
                logic.actions.toggleAllTables(true, ['Customer', 'Charge'])
                const byTable = Object.fromEntries(logic.values.databaseSchema.map((s) => [s.table, s]))
                expect(byTable['Customer'].should_sync).toBe(true)
                expect(byTable['Charge'].should_sync).toBe(false)
            } finally {
                unmount()
            }
        })

        it('toggleSchemaShouldSync(true) on a permission_error row stays off', () => {
            const blockedSchema = buildSchema({
                table: 'Charge',
                permission_error: 'Missing rak_charge_read',
            })
            const { logic, unmount } = mountWithSchemas([blockedSchema])

            try {
                logic.actions.toggleSchemaShouldSync(blockedSchema, true)
                expect(logic.values.databaseSchema[0].should_sync).toBe(false)
            } finally {
                unmount()
            }
        })

        it('toggleSchemaShouldSync(true) on a normal row still flips it on', () => {
            const okSchema = buildSchema({ table: 'Customer' })
            const { logic, unmount } = mountWithSchemas([okSchema])

            try {
                logic.actions.toggleSchemaShouldSync(okSchema, true)
                expect(logic.values.databaseSchema[0].should_sync).toBe(true)
            } finally {
                unmount()
            }
        })

        it.each([
            { name: 'cursor', incrementalField: 'Updated_At', primaryKeyColumns: null, kept: ['email'] },
            { name: 'primary key', incrementalField: null, primaryKeyColumns: ['email'], kept: ['updated_at'] },
        ])(
            'choosing a masked column as the $name drops its mask, since the server refuses it',
            ({ incrementalField, primaryKeyColumns, kept }) => {
                const users = buildSchema({ table: 'users' })
                const orders = buildSchema({ table: 'orders' })
                const { logic, unmount } = mountWithSchemas([users, orders])

                try {
                    logic.actions.setSchemaMaskedColumns(users, ['email', 'updated_at'])
                    logic.actions.setSchemaMaskedColumns(orders, ['email'])
                    logic.actions.updateSchemaSyncType(
                        users,
                        'incremental',
                        incrementalField,
                        'datetime',
                        primaryKeyColumns
                    )

                    const byTable = Object.fromEntries(logic.values.databaseSchema.map((s) => [s.table, s]))
                    expect(byTable['users'].masked_columns).toEqual(kept)
                    expect(byTable['orders'].masked_columns).toEqual(['email'])
                } finally {
                    unmount()
                }
            }
        )

        it('toggleSchemaGroup skips permission_error rows in a group', () => {
            const { logic, unmount } = mountWithSchemas([
                buildSchema({ table: 'public.customers' }),
                buildSchema({ table: 'public.charges', permission_error: 'Missing scope' }),
                buildSchema({ table: 'public.invoices' }),
            ])

            try {
                logic.actions.toggleSchemaGroup('public', true)
                const byTable = Object.fromEntries(logic.values.databaseSchema.map((s) => [s.table, s]))
                expect(byTable['public.customers'].should_sync).toBe(true)
                expect(byTable['public.invoices'].should_sync).toBe(true)
                expect(byTable['public.charges'].should_sync).toBe(false)
            } finally {
                unmount()
            }
        })

        it('explains why Next is disabled on the schema step when no table is selected', () => {
            const { logic, unmount } = mountWithSchemas([buildSchema({ table: 'Customer', should_sync: false })])

            try {
                logic.actions.setStep(3)
                expect(logic.values.canGoNext).toBe(false)
                expect(logic.values.nextButtonDisabledReason).toEqual('Select at least one table to sync')
            } finally {
                unmount()
            }
        })

        it('explains why Next is disabled when a selected table has no sync method', () => {
            const { logic, unmount } = mountWithSchemas([
                buildSchema({ table: 'Customer', should_sync: true, sync_type: null }),
            ])

            try {
                logic.actions.setStep(3)
                expect(logic.values.canGoNext).toBe(false)
                expect(logic.values.nextButtonDisabledReason).toEqual(
                    'Choose a sync method for each table you want to sync'
                )
            } finally {
                unmount()
            }
        })

        it('clears the disabled reason once a selected table has a sync method', () => {
            const { logic, unmount } = mountWithSchemas([
                buildSchema({ table: 'Customer', should_sync: true, sync_type: 'full_refresh' }),
            ])

            try {
                logic.actions.setStep(3)
                expect(logic.values.canGoNext).toBe(true)
                expect(logic.values.nextButtonDisabledReason).toBeNull()
            } finally {
                unmount()
            }
        })

        it('blocks Import on the destination step until one destination is turned on', () => {
            const { logic, unmount } = mountWithSchemas([
                buildSchema({ table: 'Customer', should_sync: true, sync_type: 'full_refresh' }),
            ])

            try {
                logic.actions.setStep(WIZARD_DESTINATION_STEP)
                logic.actions.setWizardAvailableDestinationCount(2)
                logic.actions.setWizardDestinationIds([])
                expect(logic.values.canGoNext).toBe(false)
                expect(logic.values.nextButtonDisabledReason).toEqual('Pick at least one destination')

                logic.actions.setWizardDestinationIds(['warehouse-id'])
                expect(logic.values.canGoNext).toBe(true)
                expect(logic.values.nextButtonDisabledReason).toBeNull()
            } finally {
                unmount()
            }
        })
    })

    // Onboarding one-click setup: autoConfigureTables opts every syncable table in so the user
    // can sync the whole source without touching the schema step.
    describe('autoConfigureTables', () => {
        const stripeSource = buildSourceConfig({ name: 'Stripe' })

        const apiSchema = (overrides: Partial<ExternalDataSourceSyncSchema> = {}): ExternalDataSourceSyncSchema =>
            ({
                table: 'Customer',
                label: null,
                rows: null,
                should_sync: false,
                sync_time_of_day: null,
                incremental_field: null,
                incremental_field_type: null,
                sync_type: null,
                incremental_fields: [],
                incremental_available: false,
                append_available: false,
                supports_webhooks: false,
                description: null,
                should_sync_default: true,
                primary_key_columns: null,
                available_columns: [],
                detected_primary_keys: null,
                permission_error: null,
                cdc_available: false,
                ...overrides,
            }) as ExternalDataSourceSyncSchema

        afterEach(() => {
            jest.restoreAllMocks()
        })

        it('selects every syncable table and resolves sync defaults when set', async () => {
            jest.spyOn(api.externalDataSources, 'database_schema').mockResolvedValue([
                apiSchema({
                    table: 'Customer',
                    incremental_available: true,
                    incremental_fields: [
                        { field: 'updated_at', field_type: 'datetime', label: 'updated_at', type: 'datetime' },
                    ],
                }),
                apiSchema({ table: 'Product' }),
                apiSchema({ table: 'Charge', permission_error: 'Missing scope' }),
                // Auto-configure shows no table picker, so a table the source marks default-off
                // (e.g. a Supabase Vault secrets table) must not be silently opted in.
                apiSchema({ table: 'vault.decrypted_secrets', should_sync_default: false }),
            ] as ExternalDataSourceSyncSchema[])

            const logic = sourceWizardLogic({ availableSources: { Stripe: stripeSource }, autoConfigureTables: true })
            const unmount = logic.mount()

            try {
                logic.actions.selectConnector(stripeSource)
                await expectLogic(logic, () => logic.actions.getDatabaseSchemas()).toFinishAllListeners()

                const byTable = Object.fromEntries(logic.values.databaseSchema.map((s) => [s.table, s]))
                expect(byTable['Customer'].should_sync).toBe(true)
                expect(byTable['Customer'].sync_type).toBe('incremental')
                expect(byTable['Customer'].incremental_field).toBe('updated_at')
                expect(byTable['Product'].should_sync).toBe(true)
                // permission_error rows can never be synced, even under auto-configure.
                expect(byTable['Charge'].should_sync).toBe(false)
                expect(byTable['vault.decrypted_secrets'].should_sync).toBe(false)
            } finally {
                unmount()
            }
        })

        it('honours should_sync_default when not set', async () => {
            jest.spyOn(api.externalDataSources, 'database_schema').mockResolvedValue([
                apiSchema({ table: 'Product', should_sync_default: false }),
            ] as ExternalDataSourceSyncSchema[])

            const logic = sourceWizardLogic({ availableSources: { Stripe: stripeSource } })
            const unmount = logic.mount()

            try {
                logic.actions.selectConnector(stripeSource)
                await expectLogic(logic, () => logic.actions.getDatabaseSchemas()).toFinishAllListeners()
                expect(logic.values.databaseSchema[0].should_sync).toBe(false)
            } finally {
                unmount()
            }
        })

        const column = (field: string): AvailableColumn => ({ field, label: field, type: 'string', nullable: true })

        it.each([
            ['no primary key and no id column', 'full_refresh', { available_columns: [column('updated_at')] }],
            [
                'a detected primary key',
                'incremental',
                { available_columns: [column('uuid'), column('updated_at')], detected_primary_keys: ['uuid'] },
            ],
            ['an id column', 'incremental', { available_columns: [column('ID'), column('updated_at')] }],
            ['no introspected columns', 'incremental', { available_columns: [] }],
        ])('defaults a table with %s to %s', async (_, expectedSyncType, overrides) => {
            jest.spyOn(api.externalDataSources, 'database_schema').mockResolvedValue([
                apiSchema({
                    incremental_available: true,
                    incremental_fields: [
                        { field: 'updated_at', field_type: 'datetime', label: 'updated_at', type: 'datetime' },
                    ],
                    ...overrides,
                }),
            ] as ExternalDataSourceSyncSchema[])

            const logic = sourceWizardLogic({ availableSources: { Stripe: stripeSource } })
            const unmount = logic.mount()

            try {
                logic.actions.selectConnector(stripeSource)
                await expectLogic(logic, () => logic.actions.getDatabaseSchemas()).toFinishAllListeners()
                expect(logic.values.databaseSchema[0].sync_type).toBe(expectedSyncType)
            } finally {
                unmount()
            }
        })
    })

    // Signals setup passes requiredTables to skip the schema step and sync just those tables.
    describe('requiredTables', () => {
        const githubSource = buildSourceConfig({ name: 'Github' })

        const apiSchema = (
            table: string,
            overrides: Partial<ExternalDataSourceSyncSchema> = {}
        ): ExternalDataSourceSyncSchema =>
            ({
                table,
                label: null,
                rows: null,
                should_sync: false,
                sync_time_of_day: null,
                incremental_field: null,
                incremental_field_type: null,
                sync_type: null,
                incremental_fields: [],
                incremental_available: false,
                append_available: false,
                supports_webhooks: false,
                description: null,
                should_sync_default: true,
                primary_key_columns: null,
                available_columns: [],
                detected_primary_keys: null,
                permission_error: null,
                cdc_available: false,
                ...overrides,
            }) as ExternalDataSourceSyncSchema

        const mountRequiredTablesWizard = (
            requiredTables: string[],
            requiredTableSyncType?: 'full_refresh'
        ): { logic: ReturnType<typeof sourceWizardLogic>; onComplete: jest.Mock; unmount: () => void } => {
            const onComplete = jest.fn()
            const logic = sourceWizardLogic({
                availableSources: { Github: githubSource },
                requiredTables,
                requiredTableSyncType,
                onComplete,
            })
            const unmount = logic.mount()
            logic.actions.selectConnector(githubSource)
            return { logic, onComplete, unmount }
        }

        afterEach(() => {
            jest.restoreAllMocks()
        })

        it.each([undefined, 'full_refresh'] as const)(
            'syncs readable repo-qualified rows with sync override %s',
            async (requiredTableSyncType) => {
                // Multi-repo sources name their rows `owner/repo.endpoint`, so an exact-match lookup
                // for `issues` finds nothing and the wizard bails before creating the source. The
                // payload forces should_sync on, so an unreadable row must not reach it.
                jest.spyOn(api.externalDataSources, 'database_schema').mockResolvedValue([
                    apiSchema('posthog/posthog.issues', { sync_type: 'incremental' }),
                    apiSchema('posthog/posthog-js.issues', { sync_type: 'incremental' }),
                    apiSchema('posthog/posthog.commits'),
                    apiSchema('posthog/private.issues', { permission_error: 'Requires the "Issues" permission' }),
                ] as ExternalDataSourceSyncSchema[])
                const create = jest
                    .spyOn(api.externalDataSources, 'create')
                    .mockResolvedValue({ id: 'source-1' } as Awaited<ReturnType<typeof api.externalDataSources.create>>)
                const createWebhook = jest.spyOn(api.externalDataSources, 'createWebhook')

                const { logic, onComplete, unmount } = mountRequiredTablesWizard(['issues'], requiredTableSyncType)

                try {
                    await expectLogic(logic, () => logic.actions.getDatabaseSchemas()).toFinishAllListeners()

                    expect(create).toHaveBeenCalledTimes(1)
                    expect(create.mock.calls[0][0].payload?.schemas).toEqual([
                        expect.objectContaining({
                            name: 'posthog/posthog.issues',
                            should_sync: true,
                            sync_type: requiredTableSyncType ?? 'incremental',
                        }),
                        expect.objectContaining({
                            name: 'posthog/posthog-js.issues',
                            should_sync: true,
                            sync_type: requiredTableSyncType ?? 'incremental',
                        }),
                    ])
                    // Poll-synced tables need no webhook, so completion must not wait on one.
                    expect(createWebhook).not.toHaveBeenCalled()
                    expect(onComplete).toHaveBeenCalled()
                } finally {
                    unmount()
                }
            }
        )

        // Both leave the required table unsatisfied, so neither may create a source that reports
        // setup as complete: the first would sync nothing, the second would queue a 403 sync.
        it.each([
            ['the required table is absent', [apiSchema('posthog/posthog.commits')]],
            [
                'every matching row is unreadable',
                [apiSchema('posthog/posthog.issues', { permission_error: 'Requires the "Issues" permission' })],
            ],
        ])('does not create the source when %s', async (_, discoveredSchemas) => {
            jest.spyOn(api.externalDataSources, 'database_schema').mockResolvedValue(
                discoveredSchemas as ExternalDataSourceSyncSchema[]
            )
            const create = jest.spyOn(api.externalDataSources, 'create')

            const { logic, unmount } = mountRequiredTablesWizard(['issues'])

            try {
                await expectLogic(logic, () => logic.actions.getDatabaseSchemas()).toFinishAllListeners()

                expect(create).not.toHaveBeenCalled()
                expect(logic.values.isLoading).toBe(false)
            } finally {
                unmount()
            }
        })

        it('registers the webhook before completing when a required table is webhook-synced', async () => {
            // GitHub's workflow_runs/workflow_jobs are webhook-only: without registration the
            // tables stay empty forever, while the signal reports itself as set up.
            jest.spyOn(api.externalDataSources, 'database_schema').mockResolvedValue([
                apiSchema('posthog/posthog.workflow_runs', { supports_webhooks: true }),
            ] as ExternalDataSourceSyncSchema[])
            jest.spyOn(api.externalDataSources, 'create').mockResolvedValue({ id: 'source-1' } as Awaited<
                ReturnType<typeof api.externalDataSources.create>
            >)
            const createWebhook = jest
                .spyOn(api.externalDataSources, 'createWebhook')
                .mockResolvedValue({ success: true, webhook_url: 'https://example.com/webhook' })

            const { logic, onComplete, unmount } = mountRequiredTablesWizard(['workflow_runs'])

            try {
                await expectLogic(logic, () => logic.actions.getDatabaseSchemas()).toFinishAllListeners()

                expect(createWebhook).toHaveBeenCalledWith('source-1')
                expect(onComplete).toHaveBeenCalled()
            } finally {
                unmount()
            }
        })

        it('does not complete on webhook failure, and a resubmit retries the webhook without a duplicate source', async () => {
            jest.spyOn(api.externalDataSources, 'database_schema').mockResolvedValue([
                apiSchema('posthog/posthog.workflow_runs', { supports_webhooks: true }),
            ] as ExternalDataSourceSyncSchema[])
            const create = jest.spyOn(api.externalDataSources, 'create').mockResolvedValue({
                id: 'source-1',
            } as Awaited<ReturnType<typeof api.externalDataSources.create>>)
            const createWebhook = jest
                .spyOn(api.externalDataSources, 'createWebhook')
                .mockResolvedValueOnce({
                    success: false,
                    webhook_url: '',
                    error: 'Token is missing webhook permissions',
                })
                .mockResolvedValueOnce({ success: true, webhook_url: 'https://example.com/webhook' })

            const { logic, onComplete, unmount } = mountRequiredTablesWizard(['workflow_runs'])

            try {
                await expectLogic(logic, () => logic.actions.getDatabaseSchemas()).toFinishAllListeners()

                expect(onComplete).not.toHaveBeenCalled()
                expect(logic.values.isLoading).toBe(false)

                // The source exists now, so a second submit must retry the webhook, not create again.
                await expectLogic(logic, () => logic.actions.createSource()).toFinishAllListeners()

                expect(create).toHaveBeenCalledTimes(1)
                expect(createWebhook).toHaveBeenCalledTimes(2)
                expect(createWebhook).toHaveBeenLastCalledWith('source-1')
                expect(onComplete).toHaveBeenCalled()
            } finally {
                unmount()
            }
        })
    })

    // Supabase tables carry arbitrary user columns, so the wizard only trusts update-tracking
    // columns as default cursors; anything else falls back to full refresh instead of a cursor
    // that never advances (see resolveUpdateTrackedIncrementalField).
    describe('Supabase incremental defaults', () => {
        const supabaseSource = buildSourceConfig({ name: 'Supabase' })
        const postgresSource = buildSourceConfig({ name: 'Postgres' })

        beforeEach(() => {
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WAREHOUSE_INCREMENTAL_FIELD_MODEL]: true })
        })

        const apiSchema = (
            table: string,
            overrides: Partial<ExternalDataSourceSyncSchema> = {}
        ): ExternalDataSourceSyncSchema =>
            ({
                table,
                label: null,
                rows: null,
                should_sync: false,
                sync_time_of_day: null,
                incremental_field: null,
                incremental_field_type: null,
                sync_type: null,
                incremental_fields: [],
                incremental_available: true,
                append_available: true,
                supports_webhooks: false,
                description: null,
                should_sync_default: true,
                primary_key_columns: null,
                available_columns: [],
                detected_primary_keys: null,
                permission_error: null,
                cdc_available: false,
                ...overrides,
            }) as ExternalDataSourceSyncSchema

        const dateOfBirthFields: IncrementalField[] = [
            { field: 'date_of_birth', field_type: 'date', label: 'date_of_birth', type: 'date' },
        ]

        const mountAndLoadSchemas = async (
            source: SourceConfigResponseApi
        ): Promise<{ logic: ReturnType<typeof sourceWizardLogic>; unmount: () => void }> => {
            const logic = sourceWizardLogic({ availableSources: { [source.name]: source } })
            const unmount = logic.mount()
            logic.actions.selectConnector(source)
            await expectLogic(logic, () => logic.actions.getDatabaseSchemas()).toFinishAllListeners()
            return { logic, unmount }
        }

        afterEach(() => {
            jest.restoreAllMocks()
        })

        it('defaults Supabase tables without an update-tracking column to full refresh', async () => {
            jest.spyOn(api.externalDataSources, 'database_schema').mockResolvedValue([
                apiSchema('public.users', {
                    incremental_fields: [
                        { field: 'priority', field_type: 'integer', label: 'priority', type: 'integer' },
                        ...dateOfBirthFields,
                    ],
                    incremental_field: 'priority',
                }),
                apiSchema('public.tasks', {
                    incremental_fields: [
                        { field: 'updated_at', field_type: 'timestamp', label: 'updated_at', type: 'timestamp' },
                    ],
                    incremental_field: 'updated_at',
                }),
            ] as ExternalDataSourceSyncSchema[])

            const { logic, unmount } = await mountAndLoadSchemas(supabaseSource)

            try {
                const byTable = Object.fromEntries(logic.values.databaseSchema.map((s) => [s.table, s]))
                expect(byTable['public.users'].sync_type).toBe('full_refresh')
                expect(byTable['public.tasks'].sync_type).toBe('incremental')
                expect(byTable['public.tasks'].incremental_field).toBe('updated_at')
            } finally {
                unmount()
            }
        })

        const createdAt: IncrementalField = {
            field: 'created_at',
            field_type: 'timestamp',
            label: 'created_at',
            type: 'timestamp',
        }
        const modelPick: IncrementalField = {
            field: 'fecha_actualizacion',
            field_type: 'timestamp',
            label: 'fecha_actualizacion',
            type: 'timestamp',
            recommended: true,
            picked_by_model: true,
        }

        it.each([
            {
                name: 'Postgres model pick',
                source: postgresSource,
                fields: [modelPick, createdAt],
                expected: 'fecha_actualizacion',
            },
            {
                name: 'Supabase model pick',
                source: supabaseSource,
                fields: [modelPick, createdAt],
                expected: 'fecha_actualizacion',
            },
            {
                name: 'recommended integer that is not an id',
                source: postgresSource,
                fields: [
                    { field: 'score', field_type: 'integer', label: 'score', type: 'integer', recommended: true },
                    createdAt,
                ] as IncrementalField[],
                expected: 'created_at',
            },
        ])('defaults to the recommended field: $name', async ({ source, fields, expected }) => {
            jest.spyOn(api.externalDataSources, 'database_schema').mockResolvedValue([
                apiSchema('public.orders', { incremental_fields: fields, incremental_field: fields[0].field }),
            ] as ExternalDataSourceSyncSchema[])

            const { logic, unmount } = await mountAndLoadSchemas(source)

            try {
                expect(logic.values.databaseSchema[0].incremental_field).toBe(expected)
            } finally {
                unmount()
            }
        })

        type Logic = ReturnType<typeof sourceWizardLogic>
        type RecommendationsResponse = Awaited<
            ReturnType<typeof externalDataSourcesIncrementalFieldRecommendationsCreate>
        >
        const eventTs: IncrementalField = {
            field: 'event_ts',
            field_type: 'timestamp',
            label: 'event_ts',
            type: 'timestamp',
        }

        it.each<{
            name: string
            source: SourceConfigResponseApi
            fields: IncrementalField[]
            before: (logic: Logic) => Promise<void> | void
            expected: { sync_type: string; incremental_field: string | null }
        }>([
            {
                name: 'an untouched incremental default switches to the pick',
                source: postgresSource,
                fields: [
                    { ...createdAt, recommended: true },
                    { ...modelPick, recommended: false, picked_by_model: undefined },
                ],
                before: () => {},
                expected: { sync_type: 'incremental', incremental_field: 'fecha_actualizacion' },
            },
            {
                name: 'a cursor the person changed stays',
                source: postgresSource,
                fields: [
                    { ...createdAt, recommended: true },
                    { ...modelPick, recommended: false, picked_by_model: undefined },
                ],
                before: (logic) =>
                    logic.actions.updateSchemaSyncType(
                        logic.values.databaseSchema[0],
                        'incremental',
                        'id',
                        'integer',
                        null
                    ),
                expected: { sync_type: 'incremental', incremental_field: 'id' },
            },
            {
                name: 'an untouched full-refresh default switches to incremental on the pick',
                source: supabaseSource,
                fields: [
                    { ...eventTs, recommended: true },
                    { ...modelPick, recommended: false, picked_by_model: undefined },
                ],
                before: () => {},
                expected: { sync_type: 'incremental', incremental_field: 'fecha_actualizacion' },
            },
            {
                name: 'a masked column is not picked',
                source: postgresSource,
                fields: [
                    { ...createdAt, recommended: true },
                    { ...modelPick, recommended: false, picked_by_model: undefined },
                ],
                before: (logic) =>
                    logic.actions.setSchemaMaskedColumns(logic.values.databaseSchema[0], ['fecha_actualizacion']),
                expected: { sync_type: 'incremental', incremental_field: 'created_at' },
            },
            {
                name: 'a column left out of the sync is not picked',
                source: postgresSource,
                fields: [
                    { ...createdAt, recommended: true },
                    { ...modelPick, recommended: false, picked_by_model: undefined },
                ],
                before: (logic) =>
                    logic.actions.setSchemaSyncedColumns(logic.values.databaseSchema[0], ['created_at', 'id']),
                expected: { sync_type: 'incremental', incremental_field: 'created_at' },
            },
            {
                name: 'a pick after the confirmation opened is ignored',
                source: postgresSource,
                fields: [
                    { ...createdAt, recommended: true },
                    { ...modelPick, recommended: false, picked_by_model: undefined },
                ],
                before: (logic) => {
                    logic.actions.setStep(3)
                    logic.actions.onSubmit()
                },
                expected: { sync_type: 'incremental', incremental_field: 'created_at' },
            },
            {
                name: 'an answer for an earlier discovery is ignored',
                source: postgresSource,
                fields: [
                    { ...createdAt, recommended: true },
                    { ...modelPick, recommended: false, picked_by_model: undefined },
                ],
                before: async (logic) => {
                    await expectLogic(logic, () => logic.actions.getDatabaseSchemas()).toDispatchActions([
                        'loadIncrementalFieldRecommendations',
                    ])
                },
                expected: { sync_type: 'incremental', incremental_field: 'created_at' },
            },
        ])(
            'applies a model pick that arrives later only when it still fits: $name',
            async ({ source, fields, before, expected }) => {
                jest.spyOn(api.externalDataSources, 'database_schema').mockResolvedValue([
                    apiSchema('public.orders', { incremental_fields: fields }),
                ] as ExternalDataSourceSyncSchema[])
                let resolveRecommendations: (value: RecommendationsResponse) => void = () => {}
                jest.mocked(externalDataSourcesIncrementalFieldRecommendationsCreate)
                    .mockReturnValueOnce(
                        new Promise((resolve) => {
                            resolveRecommendations = resolve
                        })
                    )
                    .mockResolvedValue({ tables: [] })

                const logic = sourceWizardLogic({ availableSources: { [source.name]: source } })
                const unmount = logic.mount()

                try {
                    logic.actions.selectConnector(source)
                    await expectLogic(logic, () => logic.actions.getDatabaseSchemas()).toDispatchActions([
                        'loadIncrementalFieldRecommendations',
                    ])
                    await before(logic)
                    await expectLogic(logic, () =>
                        resolveRecommendations({
                            tables: [
                                {
                                    table: 'public.orders',
                                    incremental_fields: [modelPick, { ...fields[0], recommended: false }],
                                },
                            ],
                        } as RecommendationsResponse)
                    ).toFinishAllListeners()

                    const orders = logic.values.databaseSchema[0]
                    expect({ sync_type: orders.sync_type, incremental_field: orders.incremental_field }).toEqual(
                        expected
                    )
                } finally {
                    unmount()
                }
            }
        )

        it('asks for recommendations in batches the endpoint accepts', async () => {
            const fields = [
                { ...createdAt, recommended: true },
                { ...eventTs, recommended: false },
            ]
            jest.spyOn(api.externalDataSources, 'database_schema').mockResolvedValue(
                Array.from({ length: 513 }, (_, n) => apiSchema(`public.t${n}`, { incremental_fields: fields }))
            )
            const recommend = jest
                .mocked(externalDataSourcesIncrementalFieldRecommendationsCreate)
                .mockReset()
                .mockResolvedValue({ tables: [] } as unknown as RecommendationsResponse)

            const { unmount } = await mountAndLoadSchemas(postgresSource)

            try {
                expect(recommend.mock.calls.map(([, body]) => body.tables.length)).toEqual([512, 1])
            } finally {
                unmount()
            }
        })

        it('keeps the picks of the batches that answered when another batch fails', async () => {
            const fields = [
                { ...createdAt, recommended: true },
                { ...modelPick, recommended: false, picked_by_model: undefined },
            ]
            jest.spyOn(api.externalDataSources, 'database_schema').mockResolvedValue(
                Array.from({ length: 513 }, (_, n) => apiSchema(`public.t${n}`, { incremental_fields: fields }))
            )
            jest.mocked(externalDataSourcesIncrementalFieldRecommendationsCreate)
                .mockReset()
                .mockRejectedValueOnce(new Error('gateway timeout'))
                .mockResolvedValueOnce({
                    tables: [
                        { table: 'public.t512', incremental_fields: [modelPick, { ...createdAt, recommended: false }] },
                    ],
                } as unknown as RecommendationsResponse)

            const { logic, unmount } = await mountAndLoadSchemas(postgresSource)

            try {
                const byTable = Object.fromEntries(logic.values.databaseSchema.map((s) => [s.table, s]))
                expect(byTable['public.t0'].incremental_field).toBe('created_at')
                expect(byTable['public.t512'].incremental_field).toBe('fecha_actualizacion')
            } finally {
                unmount()
            }
        })

        it('sends a wide table its leading candidates and keeps every column after a pick', async () => {
            const extra: IncrementalField[] = Array.from({ length: 18 }, (_, n) => ({
                field: `c${n}`,
                field_type: 'integer',
                label: `c${n}`,
                type: 'integer',
                recommended: false,
            }))
            const fields = [{ ...createdAt, recommended: true }, ...extra, { ...modelPick, recommended: false }]
            jest.spyOn(api.externalDataSources, 'database_schema').mockResolvedValue([
                apiSchema('public.wide', { incremental_fields: fields }),
            ] as ExternalDataSourceSyncSchema[])
            const sentFirst = fields.slice(0, 16)
            const recommend = jest
                .mocked(externalDataSourcesIncrementalFieldRecommendationsCreate)
                .mockReset()
                .mockResolvedValue({
                    tables: [
                        { table: 'public.wide', incremental_fields: [{ ...sentFirst[1], picked_by_model: true }] },
                    ],
                } as unknown as RecommendationsResponse)

            const { logic, unmount } = await mountAndLoadSchemas(postgresSource)

            try {
                expect(recommend.mock.calls[0][1].tables[0].incremental_fields).toHaveLength(16)
                const wide = logic.values.databaseSchema[0]
                expect(wide.incremental_fields).toHaveLength(20)
                expect(wide.incremental_fields[0].field).toBe('c0')
            } finally {
                unmount()
            }
        })

        it('asks for no recommendations without the feature flag', async () => {
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WAREHOUSE_INCREMENTAL_FIELD_MODEL]: false })
            jest.spyOn(api.externalDataSources, 'database_schema').mockResolvedValue([
                apiSchema('public.orders', {
                    incremental_fields: [
                        { ...createdAt, recommended: true },
                        { ...modelPick, recommended: false },
                    ],
                }),
            ] as ExternalDataSourceSyncSchema[])
            const recommend = jest.mocked(externalDataSourcesIncrementalFieldRecommendationsCreate).mockReset()

            const { unmount } = await mountAndLoadSchemas(postgresSource)

            try {
                expect(recommend).not.toHaveBeenCalled()
            } finally {
                unmount()
            }
        })

        it('keeps the any-timestamp fallback for other database sources', async () => {
            jest.spyOn(api.externalDataSources, 'database_schema').mockResolvedValue([
                apiSchema('public.users', {
                    incremental_fields: dateOfBirthFields,
                    incremental_field: 'date_of_birth',
                }),
            ] as ExternalDataSourceSyncSchema[])

            const { logic, unmount } = await mountAndLoadSchemas(postgresSource)

            try {
                expect(logic.values.databaseSchema[0].sync_type).toBe('incremental')
                expect(logic.values.databaseSchema[0].incremental_field).toBe('date_of_birth')
            } finally {
                unmount()
            }
        })
    })

    describe('connectError', () => {
        const stripeSource = buildSourceConfig({ name: 'Stripe' })

        afterEach(() => {
            jest.restoreAllMocks()
        })

        it('keeps a rejected connection message until the next attempt', async () => {
            jest.spyOn(api.externalDataSources, 'database_schema').mockRejectedValue({
                status: 400,
                data: { message: 'Your API key is invalid or expired.' },
            })

            const logic = sourceWizardLogic({ availableSources: { Stripe: stripeSource } })
            const unmount = logic.mount()

            try {
                logic.actions.selectConnector(stripeSource)
                await expectLogic(logic, () => logic.actions.getDatabaseSchemas()).toFinishAllListeners()
                expect(logic.values.connectError).toBe('Your API key is invalid or expired.')

                jest.spyOn(api.externalDataSources, 'database_schema').mockResolvedValue([])
                await expectLogic(logic, () => logic.actions.getDatabaseSchemas()).toFinishAllListeners()
                expect(logic.values.connectError).toBeNull()
            } finally {
                unmount()
            }
        })

        it('drops the message when another source is picked', async () => {
            jest.spyOn(api.externalDataSources, 'database_schema').mockRejectedValue({
                status: 400,
                data: { message: 'Your API key is invalid or expired.' },
            })

            const logic = sourceWizardLogic({ availableSources: { Stripe: stripeSource } })
            const unmount = logic.mount()

            try {
                logic.actions.selectConnector(stripeSource)
                await expectLogic(logic, () => logic.actions.getDatabaseSchemas()).toFinishAllListeners()
                expect(logic.values.connectError).toBe('Your API key is invalid or expired.')

                logic.actions.selectConnector(null)
                expect(logic.values.connectError).toBeNull()
            } finally {
                unmount()
            }
        })

        const sentrySource = buildSourceConfig({ name: 'Sentry' })
        const rejectProbe = (d: Deferred): void => d.reject({ status: 400, data: { message: 'Bad key.' } })
        const resolveProbe = (d: Deferred): void => d.resolve([{ table: 'charges' } as ExternalDataSourceSyncSchema])

        it.each([
            { outcome: 'rejects', picked: 'another source', switchTo: [sentrySource], settle: rejectProbe },
            { outcome: 'resolves', picked: 'another source', switchTo: [sentrySource], settle: resolveProbe },
            {
                outcome: 'rejects',
                picked: 'the same source again',
                switchTo: [sentrySource, stripeSource],
                settle: rejectProbe,
            },
            {
                outcome: 'resolves',
                picked: 'the same source again',
                switchTo: [sentrySource, stripeSource],
                settle: resolveProbe,
            },
        ])('ignores a probe that $outcome after $picked is picked', async ({ switchTo, settle }) => {
            const deferred = {} as Deferred
            jest.spyOn(api.externalDataSources, 'database_schema').mockReturnValue(
                new Promise<ExternalDataSourceSyncSchema[]>((resolve, reject) =>
                    Object.assign(deferred, { resolve, reject })
                )
            )
            const toastError = jest.spyOn(lemonToast, 'error')

            const logic = sourceWizardLogic({ availableSources: { Stripe: stripeSource, Sentry: sentrySource } })
            const unmount = logic.mount()

            try {
                logic.actions.selectConnector(stripeSource)
                logic.actions.setStep(2)
                logic.actions.getDatabaseSchemas()
                for (const source of switchTo) {
                    logic.actions.selectConnector(source)
                }
                expect(logic.values.isLoading).toBe(false)
                settle(deferred)
                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values).toMatchObject({
                    currentStep: 2,
                    connectError: null,
                    databaseSchema: [],
                    isLoading: false,
                })
                expect(toastError).not.toHaveBeenCalled()
            } finally {
                unmount()
            }
        })
    })
})
