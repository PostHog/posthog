import '~/tests/helpers/mocks/date.mock'

import { DateTime } from 'luxon'
import { inspect } from 'util'

import { closeHub, createHub } from '~/common/utils/db/hub'
import { createTestTeamFixture } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'

import { createHogExecutionGlobals, createHogFunction, insertIntegration } from '../_tests/fixtures'
import { compileHog } from '../templates/compiler'
import { HogFunctionInvocationGlobals, HogFunctionType } from '../types'
import { classifyHogError } from '../utils/hog-error-classification'
import { NATIVE_PUSH_TEMPLATE_ID } from '../utils/push-subscription-utils'
import { HogInputsService, formatHogInput, formatLiquidInput, getAppIdentifierForPush } from './hog-inputs.service'
import { RecipientTokensService } from './messaging/recipient-tokens.service'

describe('getAppIdentifierForPush', () => {
    it('returns null when no integration inputs are present', () => {
        expect(getAppIdentifierForPush({})).toBeNull()
        expect(getAppIdentifierForPush({ push_provider: { value: null } })).toBeNull()
    })

    it('returns null when integration has no project_id or bundle_id', () => {
        expect(getAppIdentifierForPush({ push_provider: { value: { key_id: 'abc' } } })).toBeNull()
    })

    it('returns project_id from a Firebase integration input', () => {
        const result = getAppIdentifierForPush({
            push_provider: { value: { project_id: 'my-firebase-project', key_id: 'abc' } },
        })
        expect(result).toBe('my-firebase-project')
    })

    it('returns bundle_id from an APNS integration input', () => {
        const result = getAppIdentifierForPush({
            push_provider: { value: { bundle_id: 'com.example.app', key_id: 'abc' } },
        })
        expect(result).toBe('com.example.app')
    })

    it('returns the first app identifier when multiple integrations are present', () => {
        const result = getAppIdentifierForPush({
            firebase_account: { value: { project_id: 'firebase-proj' } },
            apns_account: { value: { bundle_id: 'com.example.app' } },
        })
        expect(result).toBe('firebase-proj')
    })
})

describe('Hog Inputs', () => {
    let hub: Hub
    let team: Team
    let hogInputsService: HogInputsService
    let recipientTokensService: RecipientTokensService
    let integrationId1: number
    let integrationId2: number

    beforeEach(async () => {
        hub = await createHub()
        hub.SITE_URL = 'http://localhost:8000'
        team = (await createTestTeamFixture(hub.postgres)).team
        integrationId1 = team.id
        integrationId2 = team.id + 1

        const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())

        await insertIntegration(hub.postgres, team.id, {
            id: integrationId1,
            kind: 'slack',
            config: { team: 'foobar' },
            sensitive_config: {
                access_token: hub.encryptedFields.encrypt('token'),
                not_encrypted: 'not-encrypted',
            },
        })

        await insertIntegration(hub.postgres, team.id, {
            id: integrationId2,
            kind: 'oauth',
            config: { team: 'foobar', access_token: 'token' },
            sensitive_config: {
                not_encrypted: 'not-encrypted',
            },
        })

        recipientTokensService = new RecipientTokensService(hub.ENCRYPTION_SALT_KEYS, hub.SITE_URL)
        hogInputsService = new HogInputsService(hub.integrationManager, recipientTokensService, hub.encryptedFields)
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    const insertWarehouseIntegration = async (config: unknown): Promise<number> => {
        const id = team.id + 3
        await insertIntegration(hub.postgres, team.id, {
            id,
            kind: 'postgresql' as any,
            config: (typeof config === 'string' ? JSON.stringify(config) : config) as any,
            sensitive_config: { password: hub.encryptedFields.encrypt('secret-password') },
        })
        return id
    }

    describe('formatInput', () => {
        it('can handle null values in input objects', async () => {
            const globals = {
                ...createHogExecutionGlobals({
                    event: {
                        event: 'test',
                        uuid: 'test-uuid',
                    } as any,
                }),
                inputs: {},
            }

            // Body with null values that should be preserved
            const inputWithNulls = {
                body: {
                    value: {
                        event: '{event}',
                        person: null,
                        userId: null,
                    },
                },
            }

            // Call formatInput directly to test that it handles null values
            const result = await formatHogInput(inputWithNulls, globals)

            // Verify that null values are preserved
            expect(result.body.value.person).toBeNull()
            expect(result.body.value.userId).toBeNull()
            expect(result.body.value.event).toBe('{event}')
        })

        it('names a missing global in the error and keeps every other VM message out', async () => {
            const globals = createHogExecutionGlobals({ inputs: {} } as any) as any
            // {distinct_id}: GET_GLOBAL on a name the globals do not have.
            const missingGlobal = ['_H', 1, 32, 'distinct_id', 1, 1]
            await expect(formatHogInput(missingGlobal, globals, 'field')).rejects.toThrow(
                'Could not execute bytecode for input field: field: Global variable not found: distinct_id'
            )
            // dateDiff('bogus', 1, 1): the VM quotes its argument, which can be a secret input.
            const quotesArgument = ['_H', 1, 32, 'bogus', 33, 1, 33, 1, 2, 'dateDiff', 3]
            const thrown = await formatHogInput(quotesArgument, globals, 'field').then(
                () => undefined,
                (error) => error
            )
            expect(thrown.message).toMatch(/^Could not execute bytecode for input field: field$/)
            // The kind travels for the classifier; the quoted argument does not, even through a serialized cause chain.
            expect(thrown.cause).toMatchObject({ kind: 'data' })
            expect(inspect(thrown)).not.toContain('bogus')
        })

        it.each([
            ['an unsupported filter', '{{ event.event | where_exp: "i", "i" }}', 'contract'],
            ['a syntax error', '{% if %}', 'contract'],
            // The same template renders for a well-formed URL, so this failure belongs to the event.
            ['a malformed URL meeting url_decode', '{{ event.properties.url | url_decode }}', 'data'],
            [
                'a template over its memory budget',
                "{% assign s = 'aaaaaaaa' %}{% for i in (1..40) %}{% assign s = s | append: s %}{% endfor %}{{ s | size }}",
                'limit',
            ],
        ])('gives a liquid failure from %s a kind and keeps its message', (_name, template, kind) => {
            const globals = createHogExecutionGlobals({
                event: { event: '$pageview', properties: { url: '%' } } as any,
                inputs: {},
            } as any) as any
            let thrown: any
            try {
                formatLiquidInput(template, globals, 'field')
            } catch (error) {
                thrown = error
            }
            expect(thrown).toBeInstanceOf(Error)
            expect(thrown.message).toBe(thrown.cause.message)
            expect(thrown.cause).toMatchObject({ kind })
        })

        it('can handle deep null and undefined values', async () => {
            const globals = {
                ...createHogExecutionGlobals({
                    event: {
                        event: 'test',
                        uuid: 'test-uuid',
                    } as any,
                }),
                inputs: {},
            }

            const complexInput = {
                body: {
                    value: {
                        data: {
                            first: null,
                            second: undefined,
                            third: {
                                nested: null,
                            },
                        },
                    },
                },
            }

            const result = await formatHogInput(complexInput, globals)

            // Verify all null and undefined values are properly preserved
            expect(result.body.value.data.first).toBeNull()
            expect(result.body.value.data.second).toBeUndefined()
            expect(result.body.value.data.third.nested).toBeNull()
        })
    })

    describe('buildInputs', () => {
        let hogFunction: HogFunctionType
        let globals: HogFunctionInvocationGlobals

        beforeEach(async () => {
            hogFunction = createHogFunction({
                id: 'hog-function-1',
                team_id: team.id,
                name: 'Hog Function 1',
                enabled: true,
                type: 'destination',
                inputs: {
                    hog_templated: {
                        value: 'event: "{event.event}"',
                        templating: 'hog',
                        bytecode: await compileHog('return f\'event: "{event.event}"\''),
                    },
                    liquid_templated: {
                        value: 'event: "{{ event.event }}"',
                        templating: 'liquid',
                    },
                    oauth: { value: integrationId1 },
                },
                inputs_schema: [
                    { key: 'hog_templated', type: 'string', required: true },
                    { key: 'oauth', type: 'integration', required: true },
                ],
            })

            globals = createHogExecutionGlobals()
        })

        it('should template out hog inputs', async () => {
            const inputs = await hogInputsService.buildInputs(hogFunction, globals)
            expect(inputs.hog_templated).toMatchInlineSnapshot(`"event: "test""`)
        })

        it('should template out liquid inputs', async () => {
            const inputs = await hogInputsService.buildInputs(hogFunction, globals)
            expect(inputs.liquid_templated).toMatchInlineSnapshot(`"event: "test""`)
        })

        it('rejects liquid inputs whose leaves together exceed the invocation budget', async () => {
            const leaf = `{% for i in (1..600) %}${'a'.repeat(10_000)}{% endfor %}`
            hogFunction = createHogFunction({
                ...hogFunction,
                inputs: {
                    ...hogFunction.inputs,
                    liquid_object: { value: { first: leaf, second: leaf }, templating: 'liquid' },
                },
            })
            await expect(hogInputsService.buildInputs(hogFunction, globals)).rejects.toThrow(
                'liquid output limit exceeded'
            )
        })

        it('should load integration inputs and replace access tokens with placeholders', async () => {
            hogFunction = createHogFunction({
                ...hogFunction,
                inputs: {
                    hog_templated: hogFunction.inputs!.hog_templated,
                    liquid_templated: hogFunction.inputs!.liquid_templated,
                    oauth: { value: integrationId1 },
                    auth: { value: integrationId2 },
                },
                inputs_schema: [
                    { key: 'hog_templated', type: 'string', required: true },
                    { key: 'oauth', type: 'integration', required: true },
                    { key: 'auth', type: 'integration', required: true },
                ],
            })
            const inputs = await hogInputsService.buildInputs(hogFunction, globals)

            expect(inputs.oauth).toEqual({
                $integration_id: integrationId1,
                access_token: expect.any(String),
                access_token_raw: 'token',
                not_encrypted: 'not-encrypted',
                team: 'foobar',
            })
            expect(inputs.auth).toEqual({
                $integration_id: integrationId2,
                access_token: expect.any(String),
                access_token_raw: 'token',
                not_encrypted: 'not-encrypted',
                team: 'foobar',
            })
            expect(hogInputsService.acceptedAccessTokenPlaceholders(integrationId1)).toContain(
                inputs.oauth.access_token
            )
            expect(hogInputsService.acceptedAccessTokenPlaceholders(integrationId2)).toContain(inputs.auth.access_token)
        })

        it('should coerce string results to booleans for boolean schema fields', async () => {
            hogFunction.inputs = {
                is_enabled: {
                    value: 'true',
                    templating: 'liquid',
                },
            }
            hogFunction.inputs_schema = [{ key: 'is_enabled', type: 'boolean', required: false, templating: true }]

            const inputs = await hogInputsService.buildInputs(hogFunction, globals)
            expect(inputs.is_enabled).toBe(true)
        })

        it('should coerce "false" string to false for boolean schema fields', async () => {
            hogFunction.inputs = {
                is_enabled: {
                    value: 'false',
                    templating: 'liquid',
                },
            }
            hogFunction.inputs_schema = [{ key: 'is_enabled', type: 'boolean', required: false, templating: true }]

            const inputs = await hogInputsService.buildInputs(hogFunction, globals)
            expect(inputs.is_enabled).toBe(false)
        })

        it.each([
            ['was deleted', (): void => void (hogFunction.inputs!.oauth = { value: 99999999 })],
            ['belongs to a different team', (): void => void (hogFunction.team_id = 100)],
        ])('fails instead of running without the integration when it %s', async (_name, setup) => {
            setup()

            const error = await hogInputsService.buildInputs(hogFunction, globals).catch((e) => e)

            expect(error.message).toContain("The integration for input 'oauth' no longer exists.")
            // Anything but `config` parks the event and blocks DLQ replay on a failure no replay can fix.
            expect(classifyHogError(error, { runtimeContract: 'any' })).toBe('config')
        })

        it('ignores a deleted integration on a mapping this invocation does not use', async () => {
            hogFunction.mappings = [
                { inputs: { slack: { value: 99999999 } }, inputs_schema: [{ key: 'slack', type: 'integration' }] },
            ]

            await expect(hogInputsService.buildInputs(hogFunction, globals)).resolves.toBeDefined()
            await expect(
                hogInputsService.buildInputs(hogFunction, globals, hogFunction.mappings[0].inputs ?? {})
            ).rejects.toThrow("The integration for input 'slack' no longer exists.")
        })

        it('should not load a posthog connection', async () => {
            const connectionId = team.id + 2
            await insertIntegration(hub.postgres, team.id, {
                id: connectionId,
                kind: 'posthog',
                sensitive_config: { access_token: hub.encryptedFields.encrypt('connection-token') },
            })
            hogFunction.inputs = { connection: { value: connectionId } }
            hogFunction.inputs_schema = [{ key: 'connection', type: 'integration', required: true }]

            const inputs = await hogInputsService.buildInputs(hogFunction, globals)

            expect(inputs.connection).toBeNull()
        })

        it.each([
            ['a marker with a string value', { warehouse_source_type: 'Postgres', host: 'db.example.com' }],
            ['a marker with an empty string', { warehouse_source_type: '', host: 'db.example.com' }],
            ['a marker with a null value', { warehouse_source_type: null, host: 'db.example.com' }],
            ['a config that is a string', 'host=db.example.com'],
            ['a config that is an array', ['db.example.com']],
        ])('blocks an integration with %s', async (_name, config) => {
            const warehouseId = await insertWarehouseIntegration(config)
            hogFunction.inputs = { connection: { value: warehouseId } }
            hogFunction.inputs_schema = [{ key: 'connection', type: 'integration', required: true }]

            const error = await hogInputsService.buildInputs(hogFunction, globals).catch((e) => e)

            expect(error.message).toContain("The integration for input 'connection' can't be used as a function input.")
            expect(classifyHogError(error, { runtimeContract: 'any' })).toBe('config')
            const loaded = await hogInputsService.loadIntegrationInputs(hogFunction)
            expect(loaded.connection.value).toBeNull()
        })

        it.each([
            ['integration', "The integration for input 'connection' no longer exists."],
            ['integration_multi', null],
        ])("treats another team's warehouse row like a missing row for an %s input", async (type, message) => {
            const otherTeam = (await createTestTeamFixture(hub.postgres)).team
            const foreignId = 100000000 + otherTeam.id
            const missingId = foreignId + 1
            await insertIntegration(hub.postgres, otherTeam.id, {
                id: foreignId,
                kind: 'postgresql' as any,
                config: { warehouse_source_type: 'Postgres', host: 'db.example.com' },
                sensitive_config: { password: hub.encryptedFields.encrypt('secret-password') },
            })
            const run = async (id: number): Promise<any> => {
                hogFunction.inputs = { connection: { value: type === 'integration' ? id : [integrationId1, id] } }
                hogFunction.inputs_schema = [{ key: 'connection', type: type as any, required: true }]
                return hogInputsService.buildInputs(hogFunction, globals).catch((e) => e)
            }

            const foreign = await run(foreignId)
            const missing = await run(missingId)

            if (message) {
                expect(missing.message).toContain(message)
                expect(foreign.message).toBe(missing.message)
            } else {
                expect(missing).not.toBeInstanceOf(Error)
                expect(foreign).toEqual(missing)
            }
            expect(foreign.message ?? '').not.toContain("can't be used as a function input")
        })

        it.each([
            ['no marker', { team: 'foobar' }],
            ['a null config', null],
        ])('loads an integration with %s', async (_name, config) => {
            const warehouseId = await insertWarehouseIntegration({ team: 'foobar' })
            if (config === null) {
                const row = (await hub.integrationManager.getMany([warehouseId]))[warehouseId]
                jest.spyOn(hub.integrationManager, 'getMany').mockResolvedValue({
                    [warehouseId]: { ...row!, config: null as any },
                })
            }
            hogFunction.inputs = { connection: { value: warehouseId } }
            hogFunction.inputs_schema = [{ key: 'connection', type: 'integration', required: true }]

            const inputs = await hogInputsService.buildInputs(hogFunction, globals)

            expect(inputs.connection).toMatchObject({ $integration_id: warehouseId, password: 'secret-password' })
        })

        it('fails an integration_multi input that holds a marked row', async () => {
            const warehouseId = await insertWarehouseIntegration({ warehouse_source_type: 'Postgres' })
            hogFunction.inputs = { channels: { value: [integrationId1, warehouseId] } }
            hogFunction.inputs_schema = [{ key: 'channels', type: 'integration_multi', required: true }]

            await expect(hogInputsService.buildInputs(hogFunction, globals)).rejects.toThrow(
                "The integration for input 'channels' can't be used as a function input."
            )
        })

        it.each([
            { name: 'a hog function', source: undefined },
            { name: 'a workflow email step', source: { appSourceId: 'flow-1', instanceId: 'action-1' } },
        ])('should add unsubscribe url if email input is present for $name', async ({ source }) => {
            hogFunction.inputs = {
                email: {
                    templating: 'liquid',
                    value: {
                        to: { email: '{{person.properties.email}}' },
                        html: '<div>Manage subscription preferences here <a href="{{unsubscribe_url}}">here</a>Or, click <a href="{{unsubscribe_url_one_click}}">here</a> to immediately unsubscribe from all marketing emails</div>',
                    },
                },
            }

            hogFunction.inputs_schema = [{ key: 'email', type: 'native_email', required: true, templating: true }]

            const inputs = await hogInputsService.buildInputs(hogFunction, globals, undefined, source)
            expect(inputs.email.to.email).toEqual('test@posthog.com')
            const recipient = { team_id: team.id, identifier: 'test@posthog.com' }
            expect(inputs.email.html).toEqual(
                `<div>Manage subscription preferences here <a href="${recipientTokensService.generatePreferencesUrl(recipient, source)}">here</a>Or, click <a href="${recipientTokensService.generateOneClickUnsubscribeUrl(recipient, source)}">here</a> to immediately unsubscribe from all marketing emails</div>`
            )
        })

        it('escapes liquid output only in the email fields that are written into html', async () => {
            const value = '{{ event.properties.feature }}'
            globals.event.properties.feature = `Logs & "Traces" <beta>`
            hogFunction.inputs = {
                email: {
                    templating: 'liquid',
                    value: {
                        to: { email: '{{person.properties.email}}', name: value },
                        from: { email: 'hey@example.com', name: value },
                        subject: `Welcome to ${value}`,
                        text: `Welcome to ${value}`,
                        preheader: value,
                        html: `<p>${value}</p>`,
                    },
                },
            }
            hogFunction.inputs_schema = [{ key: 'email', type: 'native_email', required: true, templating: true }]

            const inputs = await hogInputsService.buildInputs(hogFunction, globals)
            const raw = `Logs & "Traces" <beta>`
            const escaped = 'Logs &amp; &#34;Traces&#34; &lt;beta&gt;'
            expect(inputs.email).toMatchObject({
                to: { name: raw },
                from: { name: raw },
                subject: `Welcome to ${raw}`,
                text: `Welcome to ${raw}`,
                preheader: escaped,
                html: `<p>${escaped}</p>`,
            })
        })

        it('renders liquid in push notification inputs without html escaping', async () => {
            globals.event.properties.feature = `Logs & "Traces" <beta>`
            hogFunction.template_id = NATIVE_PUSH_TEMPLATE_ID
            hogFunction.inputs = {
                title: { templating: 'liquid', value: 'Try {{ event.properties.feature }}' },
                body: { templating: 'liquid', value: '{{ event.properties.feature }}' },
                data: { templating: 'liquid', value: { url: 'myapp://{{ event.properties.feature }}' } },
            }
            hogFunction.inputs_schema = [
                { key: 'title', type: 'string', required: true },
                { key: 'body', type: 'string', templating: 'liquid' },
                { key: 'data', type: 'dictionary' },
            ]

            const inputs = await hogInputsService.buildInputs(hogFunction, globals)
            const raw = `Logs & "Traces" <beta>`
            expect(inputs).toMatchObject({ title: `Try ${raw}`, body: raw, data: { url: `myapp://${raw}` } })
        })

        it('drops the editor design from a liquid email instead of rendering it', async () => {
            const tag = '{% if event.event == "test" %}Hi{% endif %}'
            hogFunction.inputs = {
                email: {
                    templating: 'liquid',
                    value: {
                        to: { email: '{{person.properties.email}}' },
                        html: `<p>${tag}</p>`,
                        design: { body: { rows: [{ values: { textJson: JSON.stringify({ text: tag }) } }] } },
                    },
                },
            }
            hogFunction.inputs_schema = [{ key: 'email', type: 'native_email', required: true, templating: true }]

            const inputs = await hogInputsService.buildInputs(hogFunction, globals)
            expect(inputs.email.html).toEqual('<p>Hi</p>')
            expect(inputs.email.design).toBeUndefined()
        })

        it('resolves push subscription inputs without a push integration', async () => {
            const hogFunction = createHogFunction({
                id: 'hog-function-1',
                team_id: team.id,
                name: 'Hog Function 1',
                enabled: true,
                type: 'destination',
                inputs: {
                    push_provider: { value: integrationId1 },
                    push_subscription: { value: 'user-123' },
                },
                inputs_schema: [
                    {
                        key: 'push_provider',
                        type: 'integration',
                    },
                    {
                        key: 'push_subscription',
                        type: 'push_subscription',
                        platform: 'android',
                    },
                ],
            })

            const inputs = await hogInputsService.buildInputs(hogFunction, globals)
            expect(inputs.push_subscription).toBeNull()
        })
    })
})
