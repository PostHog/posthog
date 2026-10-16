import { KeyObject, generateKeyPairSync, verify } from 'crypto'
import { Redis } from 'ioredis'

import { CyclotronInputType } from '~/cdp/schema/cyclotron'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { RedisClient, RedisClientPipeline, RedisV2 } from '~/common/redis/redis-v2'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { createRedisFromConfig } from '~/common/utils/db/redis'
import * as requestModule from '~/common/utils/request'
import { FetchOptions, FetchResponse } from '~/common/utils/request'
import { PluginEvent } from '~/plugin-scaffold'
import { createTestMonitoringOutputs } from '~/tests/helpers/ingestion-outputs'
import { createTestTeamFixture } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'

import { insertIntegration } from '../../_tests/fixtures'
import { HogTransformerService, createHogTransformerService } from '../../hog-transformations/hog-transformer.service'
import { HogExecutorAsyncService } from '../../services/hog-executor-async.service'
import { HogExecutorService } from '../../services/hog-executor.service'
import { HogInputsService } from '../../services/hog-inputs.service'
import { EmailService } from '../../services/messaging/email.service'
import { EmailTrackingCodeSigner } from '../../services/messaging/helpers/tracking-code'
import { PushNotificationService } from '../../services/messaging/push-notification.service'
import { RecipientTokensService } from '../../services/messaging/recipient-tokens.service'
import {
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    HogFunctionInputSchemaType,
    HogFunctionInvocationGlobals,
    HogFunctionMappingTemplate,
    HogFunctionTemplate,
    HogFunctionType,
} from '../../types'
import { MAX_FETCH_TIMEOUT_MS, cdpTrackedFetch } from '../../utils/cdp-fetch'
import { buildHogFunctionInvocations } from '../../utils/invocation-utils'
import { PosthogJwtAudience } from '../../utils/jwt-utils'
import { deviceSubscriptionKey } from '../../utils/push-subscription-utils'
import { ScopedServiceJwt } from '../../utils/scoped-service-jwt'
import { compileHog, compileHogTemplate } from '../compiler'

export type TemplateCase = {
    name: string
    template: HogFunctionTemplate
    mapping?: HogFunctionMappingTemplate
}

export type OutgoingRequest = {
    url: string
    method: string
    headers: Record<string, string>
    body?: string
}

export type ResponseScenario = {
    status: number
    body: unknown
    /** Quotes the request back in the response body, the way some APIs report a rejected call. */
    echoRequest?: boolean
}

export type RunOptions = {
    /** Turns on every boolean input whose key mentions debug, so templates print what they send. */
    debug?: boolean
}

export type PipelineRun = {
    invocationErrors: string[]
    result?: CyclotronJobInvocationResult
    /** A throw rejects the whole batch in production, so it is never a visible failure of one invocation. */
    thrown?: string
    requests: OutgoingRequest[]
    printedOutput: string[]
    sensitiveValues: string[]
    connections: Connection[]
}

export type Connection = {
    kind: string
    credentialIn: (requestText: string) => string | undefined
}

type FakeConnection = Connection & {
    config: Record<string, unknown>
    secrets: Record<string, string>
    pushDevice?: { app: string; token: string }
}

const EXECUTION_BUDGET_MS = 5000
const FETCH_RETRIES = 3
const FETCH_BACKOFF_BASE_MS = 100
const FETCH_BACKOFF_MAX_MS = 1000
// Django compiles filters to bytecode. The event name already targets the mapping, so matching everything is safe.
const MATCH_ALL_FILTERS = { bytecode: ['_h', 29] }
const MAX_ASYNC_FUNCTIONS = 10

// Mirrors the input types validation.py compiles to bytecode. Every other type reaches the VM as its raw value.
const TRANSPILED_INPUT_TYPES = new Set<HogFunctionInputSchemaType['type']>([
    'string',
    'boolean',
    'dictionary',
    'json',
    'email',
    'native_email',
    'posthog_ticket_tags',
    'customer_analytics_account_properties',
    'customer_analytics_account_relationships',
])

export const casesFor = (templates: HogFunctionTemplate[]): TemplateCase[] =>
    templates
        .filter((template) => template.code_language === 'hog')
        .flatMap((template) =>
            template.mapping_templates?.length
                ? template.mapping_templates.map((mapping) => ({
                      name: `${template.id} > ${mapping.name}`,
                      template,
                      mapping,
                  }))
                : [{ name: template.id, template }]
        )

export class TemplatePipeline {
    private requests: OutgoingRequest[] = []
    private response: ResponseScenario = { status: 200, body: {} }

    private constructor(
        private hub: Hub,
        private redis: Redis,
        private team: Team,
        private executor: HogExecutorAsyncService,
        private hogInputsService: HogInputsService,
        private transformer: HogTransformerService
    ) {}

    static async start(): Promise<TemplatePipeline> {
        const hub = await createHub()
        const { team } = await createTestTeamFixture(hub.postgres)
        const recipientTokensService = new RecipientTokensService(hub.ENCRYPTION_SALT_KEYS, hub.SITE_URL)
        const hogInputsService = new HogInputsService(
            hub.integrationManager,
            recipientTokensService,
            hub.encryptedFields
        )
        const redis = await createRedisFromConfig(
            hub.CDP_REDIS_HOST
                ? { url: hub.CDP_REDIS_HOST, options: { port: hub.CDP_REDIS_PORT, password: hub.CDP_REDIS_PASSWORD } }
                : { url: hub.REDIS_URL }
        )
        const pushNotificationService = new PushNotificationService(
            hub.integrationManager,
            hub.encryptedFields,
            {
                trackedFetch: cdpTrackedFetch,
                maxFetchTimeoutMs: MAX_FETCH_TIMEOUT_MS,
                maxRetries: FETCH_RETRIES,
                backoffBaseMs: FETCH_BACKOFF_BASE_MS,
                backoffMaxMs: FETCH_BACKOFF_MAX_MS,
            },
            singleClientRedisV2(redis)
        )
        const executor = new HogExecutorAsyncService(
            new HogExecutorService({ executionTimeoutMs: EXECUTION_BUDGET_MS }, hogInputsService),
            {
                googleAdwordsDeveloperToken: 'fake-developer-token',
                fetchRetries: FETCH_RETRIES,
                fetchBackoffBaseMs: FETCH_BACKOFF_BASE_MS,
                fetchBackoffMaxMs: FETCH_BACKOFF_MAX_MS,
                siteUrl: hub.SITE_URL,
                internalApiBaseUrl: hub.INTERNAL_API_BASE_URL,
            },
            {
                teamManager: hub.teamManager,
                conversationsTicketsJwt: new ScopedServiceJwt(
                    PosthogJwtAudience.CONVERSATIONS_TICKETS,
                    'fake-jwt-secret'
                ),
                customerAnalyticsAccountsJwt: new ScopedServiceJwt(
                    PosthogJwtAudience.CUSTOMER_ANALYTICS_ACCOUNTS,
                    'fake-jwt-secret'
                ),
                hogInputsService,
                emailService: new EmailService(
                    {
                        sesAccessKeyId: hub.SES_ACCESS_KEY_ID,
                        sesSecretAccessKey: hub.SES_SECRET_ACCESS_KEY,
                        sesRegion: hub.SES_REGION,
                        sesEndpoint: hub.SES_ENDPOINT,
                        sesTrackedConfigurationSet: hub.SES_TRACKED_CONFIGURATION_SET,
                        sesUntrackedConfigurationSet: hub.SES_UNTRACKED_CONFIGURATION_SET,
                    },
                    hub.integrationManager,
                    undefined as any,
                    hub.ENCRYPTION_SALT_KEYS,
                    hub.SITE_URL,
                    new EmailTrackingCodeSigner(hub.ENCRYPTION_SALT_KEYS, hub.CDP_EMAIL_TRACKING_URL),
                    undefined as any,
                    undefined as any
                ),
                recipientTokensService,
                pushNotificationService,
            }
        )
        const transformer = createHogTransformerService(
            { ...hub, TRANSFORMATIONS_HOG_TIMEOUT_MS: EXECUTION_BUDGET_MS, CDP_HOG_RUST_VM_EXECUTION_ENABLED: false },
            { ...hub, monitoringOutputs: createTestMonitoringOutputs(undefined as unknown as KafkaProducerWrapper) }
        )
        const pipeline = new TemplatePipeline(hub, redis, team, executor, hogInputsService, transformer)
        pipeline.interceptNetwork()
        return pipeline
    }

    async stop(): Promise<void> {
        jest.restoreAllMocks()
        await this.redis.quit()
        await closeHub(this.hub)
    }

    async run(templateCase: TemplateCase, response: ResponseScenario, options: RunOptions = {}): Promise<PipelineRun> {
        this.requests = []
        this.response = response

        const { hogFunction, connections } = await this.createHogFunction(templateCase, options)
        const globals = this.representativeGlobals(templateCase, connections)
        const sensitiveValues = [
            ...this.sensitiveInputValues(hogFunction),
            ...connections.flatMap((connection) => Object.values(connection.secrets)),
            ...connections.flatMap((connection) => (connection.pushDevice ? [connection.pushDevice.token] : [])),
        ]

        if (hogFunction.type === 'transformation') {
            const { invocationResults } = await this.transformer.transformEvent(pluginEventFrom(globals), [hogFunction])
            const result = invocationResults[0]
            return {
                invocationErrors: result ? [] : ['the transformation did not run'],
                result,
                requests: this.requests,
                printedOutput: result?.logs.map((log) => log.message) ?? [],
                sensitiveValues,
                connections,
            }
        }

        const { invocations, buildFailures } = await buildHogFunctionInvocations(
            this.hogInputsService,
            [hogFunction],
            globals
        )
        const invocationErrors = buildFailures.map((failure) => `${failure.step}: ${failure.error}`)

        if (invocations.length !== 1) {
            invocationErrors.push(`expected 1 invocation, got ${invocations.length}`)
        }
        const { result, thrown } = invocations.length === 1 ? await this.execute(invocations[0]) : {}

        return {
            invocationErrors,
            result,
            thrown,
            requests: this.requests,
            printedOutput: result?.logs.map((log) => log.message) ?? [],
            sensitiveValues,
            connections,
        }
    }

    private async execute(
        invocation: CyclotronJobInvocationHogFunction
    ): Promise<{ result?: CyclotronJobInvocationResult; thrown?: string }> {
        try {
            return {
                result: await this.executor.executeWithAsyncFunctions(invocation, {
                    maxAsyncFunctions: MAX_ASYNC_FUNCTIONS,
                }),
            }
        } catch (error) {
            return { thrown: `execution threw: ${String(error)}` }
        }
    }

    private interceptNetwork(): void {
        const respond = (url: string, options: FetchOptions = {}): Promise<FetchResponse> => {
            const request: OutgoingRequest = {
                url,
                method: options.method ?? 'GET',
                headers: (options.headers as Record<string, string>) ?? {},
                body: typeof options.body === 'string' ? options.body : undefined,
            }
            this.requests.push(request)
            const { status, echoRequest } = this.response
            const body = echoRequest ? { error: 'Request rejected', request } : this.response.body
            return Promise.resolve({
                status,
                headers: { 'content-type': 'application/json' },
                json: () => Promise.resolve(body),
                text: () => Promise.resolve(JSON.stringify(body)),
                dump: () => Promise.resolve(),
            })
        }
        jest.spyOn(requestModule, 'fetch').mockImplementation(respond)
        jest.spyOn(requestModule, 'internalFetch').mockImplementation(respond)
    }

    private async createHogFunction(
        templateCase: TemplateCase,
        options: RunOptions
    ): Promise<{ hogFunction: HogFunctionType; connections: FakeConnection[] }> {
        const { template, mapping } = templateCase
        const connections: FakeConnection[] = []
        const values: Record<string, unknown> = {}

        for (const schema of template.inputs_schema) {
            if (schema.type === 'integration') {
                const connection = fakeConnection(schema.integration ?? '', schema.key)
                connections.push(connection)
                values[schema.key] = await this.insertIntegration(connection)
            } else if (schema.type === 'integration_multi') {
                const kindConnections = (schema.integration ?? '').split(',').map((kind) => fakeConnection(kind, kind))
                connections.push(...kindConnections)
                values[schema.key] = await Promise.all(kindConnections.map((c) => this.insertIntegration(c)))
            } else {
                values[schema.key] =
                    options.debug && schema.type === 'boolean' && /debug/i.test(schema.key)
                        ? true
                        : representativeValue(schema)
            }
        }

        const inputs: Record<string, CyclotronInputType> = {}
        const encryptedInputs: Record<string, CyclotronInputType> = {}
        const order = dependencyOrder(values)
        for (const schema of template.inputs_schema) {
            if (values[schema.key] === undefined) {
                continue
            }
            const target = schema.secret ? encryptedInputs : inputs
            target[schema.key] = { ...(await compileInput(schema, values[schema.key])), order: order[schema.key] }
        }

        const mappings = mapping
            ? [
                  {
                      ...mapping,
                      filters: { ...mapping.filters, ...MATCH_ALL_FILTERS },
                      inputs: await compileMappingInputs(mapping),
                  },
              ]
            : null

        const { code, ...rest } = template
        const hogFunction: HogFunctionType = {
            ...rest,
            id: `contract-${template.id}`,
            team_id: this.team.id,
            enabled: true,
            deleted: false,
            hog: code,
            bytecode: await compileHog(code),
            inputs,
            encrypted_inputs: encryptedInputs,
            filters: MATCH_ALL_FILTERS,
            mappings,
            template_id: template.id,
            created_at: '2025-01-01T00:00:00Z',
            updated_at: '2025-01-01T00:00:00Z',
        }

        return { hogFunction, connections }
    }

    private async insertIntegration({ kind, config, secrets }: FakeConnection): Promise<number> {
        const integration = await insertIntegration(this.hub.postgres, this.team.id, {
            kind: kind as any,
            config,
            sensitive_config: Object.fromEntries(
                Object.entries(secrets).map(([key, value]) => [key, this.hub.encryptedFields.encrypt(value)])
            ),
        })
        return integration.id
    }

    // The subscription endpoint stores each device token encrypted on the person it registers for.
    private pushSubscriptions(connections: FakeConnection[]): Record<string, string> {
        return Object.fromEntries(
            connections
                .flatMap((connection) => (connection.pushDevice ? [connection.pushDevice] : []))
                .map(({ app, token }) => [deviceSubscriptionKey(app, token), this.hub.encryptedFields.encrypt(token)])
        )
    }

    private sensitiveInputValues(hogFunction: HogFunctionType): string[] {
        return Object.values(hogFunction.encrypted_inputs ?? {})
            .map((input) => input.value)
            .filter((value): value is string => typeof value === 'string')
    }

    private representativeGlobals(
        templateCase: TemplateCase,
        connections: FakeConnection[]
    ): HogFunctionInvocationGlobals {
        const projectUrl = `https://us.posthog.com/project/${this.team.id}`
        const eventName = eventNameFor(templateCase)
        return {
            project: { id: this.team.id, name: 'Example project', url: projectUrl },
            event: {
                uuid: '01920000-0000-7000-8000-000000000001',
                event: eventName,
                distinct_id: 'example-distinct-id',
                elements_chain: '',
                timestamp: '2025-01-01T00:00:00.000Z',
                url: `${projectUrl}/events/01920000-0000-7000-8000-000000000001`,
                properties: {
                    $current_url: 'https://example.com/pricing?utm_source=newsletter',
                    $pathname: '/pricing',
                    $host: 'example.com',
                    $browser: 'Chrome',
                    $os: 'Mac OS X',
                    $ip: '203.0.113.10',
                    $lib: 'web',
                    $session_id: '01920000-0000-7000-8000-000000000002',
                    email: 'ada@example.com',
                    order_id: 'order-1001',
                    ticket_id: '01920000-0000-7000-8000-000000000004',
                    revenue: 42.5,
                    price: 42.5,
                    currency: 'USD',
                    products: [{ product_id: 'sku-1', name: 'Example product', price: 42.5, quantity: 1 }],
                    ...SYSTEM_EVENT_PROPERTIES[eventName],
                },
            },
            person: {
                id: '01920000-0000-7000-8000-000000000003',
                name: 'Ada Example',
                url: `${projectUrl}/person/example-distinct-id`,
                properties: {
                    email: 'ada@example.com',
                    name: 'Ada Example',
                    first_name: 'Ada',
                    last_name: 'Example',
                    phone: '+15555550100',
                    $geoip_country_code: 'US',
                    $geoip_city_name: 'Springfield',
                    ...this.pushSubscriptions(connections),
                },
            },
            groups: {
                company: {
                    id: 'example-company',
                    type: 'company',
                    index: 0,
                    url: `${projectUrl}/groups/0/example-company`,
                    properties: { name: 'Example Inc', domain: 'example.com' },
                },
            },
        }
    }
}

// The non-secret part of a connection that templates read, keyed by integration kind.
const INTEGRATION_CONFIGS: Record<string, Record<string, unknown>> = {
    github: { account: { name: 'example-org' } },
    gitlab: { hostname: 'https://gitlab.example.com', project_id: 1001 },
    slack: { scope: 'chat:write,chat:write.customize', team: { id: 'T0000EXAMPLE', name: 'Example workspace' } },
    twilio: { account_sid: 'ACexample0000' },
}

const APNS_SIGNING_KEY = generateKeyPairSync('ec', { namedCurve: 'prime256v1' })

const fakeConnection = (kind: string, key: string): FakeConnection => {
    switch (kind) {
        case 'firebase':
            return {
                ...tokenConnection(
                    kind,
                    { project_id: 'example-firebase-project' },
                    {
                        access_token: `fake-access-token-${key}-0000`,
                    }
                ),
                pushDevice: { app: 'example-firebase-project', token: 'fake-fcm-device-token-0000' },
            }
        case 'apns':
            return {
                kind,
                config: {
                    team_id: 'EXAMPLETM1',
                    key_id: 'EXAMPLEKY1',
                    bundle_id: 'com.example.app',
                    environment: 'production',
                },
                secrets: {
                    signing_key: APNS_SIGNING_KEY.privateKey.export({ type: 'pkcs8', format: 'pem' }).toString(),
                },
                credentialIn: jwtSignedBy(APNS_SIGNING_KEY.publicKey),
                pushDevice: { app: 'com.example.app', token: '0123456789abcdef'.repeat(4) },
            }
        default:
            return tokenConnection(kind, INTEGRATION_CONFIGS[kind] ?? {}, fakeIntegrationCredentials(key))
    }
}

const tokenConnection = (
    kind: string,
    config: Record<string, unknown>,
    secrets: Record<string, string>
): FakeConnection => ({
    kind,
    config,
    secrets,
    credentialIn: (requestText) => Object.values(secrets).find((secret) => requestText.includes(secret)),
})

const BEARER_JWT = /\bbearer (([\w-]+\.[\w-]+)\.([\w-]+))/gi

// The signing key never leaves the pod, so the request carries a token signed with it instead.
const jwtSignedBy =
    (publicKey: KeyObject) =>
    (requestText: string): string | undefined =>
        [...requestText.matchAll(BEARER_JWT)].find(([, , signingInput, signature]) =>
            verify(
                'SHA256',
                Buffer.from(signingInput),
                { key: publicKey, dsaEncoding: 'ieee-p1363' },
                Buffer.from(signature, 'base64url')
            )
        )?.[1]

// A pool would keep its idle connection open after the suite, and hold the jest process alive with it.
const singleClientRedisV2 = (redis: Redis): RedisV2 => ({
    useClient: (_options, callback) => callback(redis as unknown as RedisClient),
    usePipeline: (_options, callback) => {
        const pipeline = redis.pipeline()
        callback(pipeline as unknown as RedisClientPipeline)
        return pipeline.exec()
    },
})

const pluginEventFrom = (globals: HogFunctionInvocationGlobals): PluginEvent => ({
    uuid: globals.event.uuid,
    event: globals.event.event,
    distinct_id: globals.event.distinct_id,
    properties: { ...globals.event.properties },
    timestamp: globals.event.timestamp,
    ip: String(globals.event.properties.$ip),
    site_url: 'https://us.posthog.com',
    team_id: globals.project.id,
    now: globals.event.timestamp,
})

const fakeIntegrationCredentials = (key: string): Record<string, string> => ({
    access_token: `fake-access-token-${key}-0000`,
    auth_token: `fake-auth-token-${key}-0000`,
})

// Properties PostHog always sends with these system events.
const SYSTEM_EVENT_PROPERTIES: Record<string, Record<string, unknown>> = {
    $pageview: { title: 'Pricing' },
    $screen: { $screen_name: 'Pricing' },
    $identify: { $anon_distinct_id: 'example-anonymous-id', $set: { email: 'ada@example.com' } },
    $groupidentify: { $group_type: 'company', $group_key: 'example-company', $group_set: { name: 'Example Inc' } },
}

const HOGQL_EVENT_NAME = /\bevent\s*(?:in\s*\(|=)\s*'([^']+)'/

// Mapping filters name their event either as the event id or in a HogQL property such as `event in ('$pageview')`.
const eventNameFor = ({ mapping }: TemplateCase): string => {
    const firstEvent = mapping?.filters?.events?.[0]
    if (typeof firstEvent?.id === 'string') {
        return firstEvent.id
    }
    for (const property of firstEvent?.properties ?? []) {
        const match = HOGQL_EVENT_NAME.exec(String(property.key))
        if (match) {
            return match[1]
        }
    }
    return 'order_completed'
}

// Secrets whose format the template checks before it sends anything.
const SECRET_VALUES: Record<string, string> = {
    signing_secret: Buffer.from('fake-signing-secret-0000').toString('base64'),
}

const representativeValue = (schema: HogFunctionInputSchemaType): unknown => {
    const needsGeneratedValue =
        (schema.default === undefined || schema.default === '') && (schema.required || schema.secret)
    if (!needsGeneratedValue) {
        return schema.default
    }
    if (schema.secret) {
        return SECRET_VALUES[schema.key] ?? `fake-secret-${schema.key}-0000`
    }
    if (schema.choices?.length) {
        return schema.choices[0].value
    }
    switch (schema.type) {
        case 'number':
            return 1
        case 'boolean':
            return true
        case 'dictionary':
        case 'json':
        case 'customer_analytics_account_properties':
        case 'customer_analytics_account_relationships':
            return { example_key: 'example-value' }
        case 'posthog_ticket_tags':
            return ['example-tag']
        default:
            return representativeString(schema.key)
    }
}

const representativeString = (key: string): string => {
    const lowerKey = key.toLowerCase()
    if (lowerKey.includes('url')) {
        return 'https://example.com/hook'
    }
    if (lowerKey.includes('email')) {
        return 'ada@example.com'
    }
    if (lowerKey.includes('phone') || lowerKey.includes('number')) {
        return '+15555550100'
    }
    return `example-${key}`
}

const compileInput = async (schema: HogFunctionInputSchemaType, value: unknown): Promise<CyclotronInputType> => {
    if (schema.templating === false) {
        return { value }
    }
    if (schema.templating === 'liquid') {
        return { value, templating: 'liquid' }
    }
    if (!value || !TRANSPILED_INPUT_TYPES.has(schema.type)) {
        return { value, templating: 'hog' }
    }
    return { value, templating: 'hog', bytecode: await compileTemplateValue(value) }
}

const compileMappingInputs = async (
    mapping: HogFunctionMappingTemplate
): Promise<Record<string, CyclotronInputType>> => {
    const schemas = mapping.inputs_schema ?? []
    const values = Object.fromEntries(schemas.map((schema) => [schema.key, representativeValue(schema)]))
    const order = dependencyOrder(values)
    const inputs: Record<string, CyclotronInputType> = {}
    for (const schema of schemas) {
        if (values[schema.key] !== undefined) {
            inputs[schema.key] = { ...(await compileInput(schema, values[schema.key])), order: order[schema.key] }
        }
    }
    return inputs
}

const INPUT_REFERENCE = /\binputs\.([A-Za-z_$][\w$]*)/g

// validation.py orders inputs so that an input which reads `inputs.<key>` runs after that key.
const dependencyOrder = (values: Record<string, unknown>): Record<string, number> => {
    const keys = Object.keys(values).filter((key) => values[key] !== undefined)
    const dependencies = Object.fromEntries(
        keys.map((key) => [
            key,
            [...JSON.stringify(values[key]).matchAll(INPUT_REFERENCE)]
                .map((match) => match[1])
                .filter((dependency) => dependency !== key && keys.includes(dependency)),
        ])
    )
    const sorted: string[] = []
    const visit = (key: string, path: Set<string>): void => {
        if (sorted.includes(key) || path.has(key)) {
            return
        }
        dependencies[key].forEach((dependency) => visit(dependency, new Set([...path, key])))
        sorted.push(key)
    }
    keys.forEach((key) => visit(key, new Set()))
    return Object.fromEntries(sorted.map((key, index) => [key, index]))
}

const compileTemplateValue = async (value: unknown): Promise<unknown> => {
    if (typeof value === 'string') {
        return await compileHogTemplate(value)
    }
    if (Array.isArray(value)) {
        return await Promise.all(value.map(compileTemplateValue))
    }
    if (value && typeof value === 'object') {
        const entries = await Promise.all(
            Object.entries(value).map(async ([key, item]) => [key, await compileTemplateValue(item)] as const)
        )
        return Object.fromEntries(entries)
    }
    return value
}
