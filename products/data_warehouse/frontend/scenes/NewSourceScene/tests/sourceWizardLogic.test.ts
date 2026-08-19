import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import type { SourceConfig } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import type { ExternalDataSourceSyncSchema, IncrementalField } from '~/types'

import {
    buildKeaFormDefaultFromSourceDetails,
    getDatabaseSchemaPayload,
    getErrorsForFields,
    mergeRestoredSourceFormValues,
    resolveConnectErrorMessage,
    shouldHydrateSourceFromUrl,
    sourceWizardLogic,
} from '../sourceWizardLogic'

describe('sourceWizardLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('shares a single wizard instance across references with the same props', () => {
        const postgresSource = {
            name: 'Postgres',
            iconPath: '',
            caption: null,
            fields: [],
        } as SourceConfig
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
        const postgresSource = {
            name: 'Postgres',
            iconPath: '',
            caption: null,
            fields: [],
        } as SourceConfig
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

    it('does not hydrate the same source URL again after the wizard has started', () => {
        const postgresSource = {
            name: 'Postgres',
            iconPath: '',
            caption: null,
            fields: [],
        } as SourceConfig

        expect(shouldHydrateSourceFromUrl(2, postgresSource, postgresSource, 'direct', 'direct')).toBe(false)
        expect(shouldHydrateSourceFromUrl(1, postgresSource, postgresSource, 'direct', 'direct')).toBe(true)
        expect(shouldHydrateSourceFromUrl(2, postgresSource, postgresSource, 'warehouse', 'direct')).toBe(true)
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

        it('never returns undefined for a 4xx with no message body', () => {
            const message = resolveConnectErrorMessage({ status: 400 })
            expect(message).toBeTruthy()
            expect(message).not.toEqual('undefined')
        })
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
                Test: {
                    name: 'Stripe',
                    iconPath: '',
                    caption: null,
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
                },
            })

            expect(res).toEqual({ prefix: '', description: '', payload: { test_field: '' } })
        })

        it('returns defaults for pure select field', async () => {
            const sourceWizardLogic = await import('../sourceWizardLogic')
            const res = sourceWizardLogic.buildKeaFormDefaultFromSourceDetails({
                Test: {
                    name: 'Stripe',
                    iconPath: '',
                    caption: null,
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
                },
            })

            expect(res).toEqual({ prefix: '', description: '', payload: { test_field: 'value1' } })
        })

        it('returns an array default for a multiple select field', async () => {
            const sourceWizardLogic = await import('../sourceWizardLogic')
            const res = sourceWizardLogic.buildKeaFormDefaultFromSourceDetails({
                Test: {
                    name: 'GoogleSearchConsole',
                    iconPath: '',
                    caption: null,
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
                },
            })

            expect(res).toEqual({ prefix: '', description: '', payload: { search_types: ['web'] } })
        })

        it('returns defaults for select field with fields', async () => {
            const sourceWizardLogic = await import('../sourceWizardLogic')
            const res = sourceWizardLogic.buildKeaFormDefaultFromSourceDetails({
                Test: {
                    name: 'Stripe',
                    iconPath: '',
                    caption: null,
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
                },
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
                Test: {
                    name: 'Stripe',
                    iconPath: '',
                    caption: null,
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
                },
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
                Test: {
                    name: 'Stripe',
                    iconPath: '',
                    caption: null,
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
                },
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
        const stripeSource = {
            name: 'Stripe',
            iconPath: '',
            caption: null,
            fields: [],
        } as SourceConfig

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

            try {
                logic.actions.toggleAllTables(true)
                let byTable = Object.fromEntries(logic.values.databaseSchema.map((s) => [s.table, s]))
                expect(byTable['Customer'].should_sync).toBe(true)
                expect(byTable['vault.decrypted_secrets'].should_sync).toBe(false)
                expect(byTable['vault.secrets'].should_sync).toBe(true)

                logic.actions.toggleAllTables(false)
                byTable = Object.fromEntries(logic.values.databaseSchema.map((s) => [s.table, s]))
                expect(byTable['vault.secrets'].should_sync).toBe(false)
            } finally {
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
    })

    // Onboarding one-click setup: autoConfigureTables opts every syncable table in so the user
    // can sync the whole source without touching the schema step.
    describe('autoConfigureTables', () => {
        const stripeSource = {
            name: 'Stripe',
            iconPath: '',
            caption: null,
            fields: [],
        } as SourceConfig

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
    })

    // Signals setup passes requiredTables to skip the schema step and sync just those tables.
    describe('requiredTables', () => {
        const githubSource = {
            name: 'Github',
            iconPath: '',
            caption: null,
            fields: [],
        } as SourceConfig

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
            requiredTables: string[]
        ): { logic: ReturnType<typeof sourceWizardLogic>; onComplete: jest.Mock; unmount: () => void } => {
            const onComplete = jest.fn()
            const logic = sourceWizardLogic({
                availableSources: { Github: githubSource },
                requiredTables,
                onComplete,
            })
            const unmount = logic.mount()
            logic.actions.selectConnector(githubSource)
            return { logic, onComplete, unmount }
        }

        afterEach(() => {
            jest.restoreAllMocks()
        })

        it('syncs every repo-qualified row the credentials can read', async () => {
            // Multi-repo sources name their rows `owner/repo.endpoint`, so an exact-match lookup
            // for `issues` finds nothing and the wizard bails before creating the source. The
            // payload forces should_sync on, so an unreadable row must not reach it.
            jest.spyOn(api.externalDataSources, 'database_schema').mockResolvedValue([
                apiSchema('posthog/posthog.issues'),
                apiSchema('posthog/posthog-js.issues'),
                apiSchema('posthog/posthog.commits'),
                apiSchema('posthog/private.issues', { permission_error: 'Requires the "Issues" permission' }),
            ] as ExternalDataSourceSyncSchema[])
            const create = jest
                .spyOn(api.externalDataSources, 'create')
                .mockResolvedValue({ id: 'source-1' } as Awaited<ReturnType<typeof api.externalDataSources.create>>)
            const createWebhook = jest.spyOn(api.externalDataSources, 'createWebhook')

            const { logic, onComplete, unmount } = mountRequiredTablesWizard(['issues'])

            try {
                await expectLogic(logic, () => logic.actions.getDatabaseSchemas()).toFinishAllListeners()

                expect(create).toHaveBeenCalledTimes(1)
                expect(create.mock.calls[0][0].payload?.schemas).toEqual([
                    expect.objectContaining({ name: 'posthog/posthog.issues', should_sync: true }),
                    expect.objectContaining({ name: 'posthog/posthog-js.issues', should_sync: true }),
                ])
                // Poll-synced tables need no webhook, so completion must not wait on one.
                expect(createWebhook).not.toHaveBeenCalled()
                expect(onComplete).toHaveBeenCalled()
            } finally {
                unmount()
            }
        })

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
        const supabaseSource = { name: 'Supabase', iconPath: '', caption: null, fields: [] } as SourceConfig
        const postgresSource = { name: 'Postgres', iconPath: '', caption: null, fields: [] } as SourceConfig

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
            source: SourceConfig
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
})
