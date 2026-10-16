import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'

import { createHmac } from 'crypto'

import { CyclotronInputType } from '~/cdp/schema/cyclotron'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { closeHub, createHub } from '~/common/utils/db/hub'
import * as requestModule from '~/common/utils/request'
import { FetchOptions, FetchResponse } from '~/common/utils/request'
import { encodeLogAttributeValue } from '~/logs/attribute-value'
import type { LogRecord } from '~/logs/log-record-avro'
import { ATTR_TRANSFORMATIONS_FAILED, LogsTransformerService } from '~/logs/transformations/logs-transformer.service'
import { PluginEvent } from '~/plugin-scaffold'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { createTestMonitoringOutputs } from '~/tests/helpers/ingestion-outputs'
import { createTestTeamFixture } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'

import { insertIntegration } from '../../_tests/fixtures'
import {
    CdpSourceWebhooksConsumer,
    HogFunctionWebhookResult,
    SourceWebhookRequest,
    getCustomHttpResponse,
} from '../../consumers/cdp-source-webhooks.consumer'
import { HogTransformerService, createHogTransformerService } from '../../hog-transformations/hog-transformer.service'
import { HogExecutorAsyncService } from '../../services/hog-executor-async.service'
import { HogExecutorService } from '../../services/hog-executor.service'
import { HogInputsService } from '../../services/hog-inputs.service'
import { HogFunctionManagerService } from '../../services/managers/hog-function-manager.service'
import { EmailService } from '../../services/messaging/email.service'
import { EmailTrackingCodeSigner } from '../../services/messaging/helpers/tracking-code'
import { RecipientTokensService } from '../../services/messaging/recipient-tokens.service'
import { HogFunctionMonitoringService } from '../../services/monitoring/hog-function-monitoring.service'
import {
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    HogFunctionInputSchemaType,
    HogFunctionInvocationGlobals,
    HogFunctionMappingTemplate,
    HogFunctionTemplate,
    HogFunctionType,
} from '../../types'
import { buildHogFunctionInvocations } from '../../utils/invocation-utils'
import { PosthogJwtAudience } from '../../utils/jwt-utils'
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
    /** Sends a source webhook request whose credentials do not match the configured secrets. */
    forgedCredentials?: boolean
}

export type PipelineRun = {
    invocationErrors: string[]
    result?: CyclotronJobInvocationResult
    /** A throw rejects the whole batch in production, so it is never a visible failure of one invocation. */
    thrown?: string
    requests: OutgoingRequest[]
    printedOutput: string[]
    httpResponse?: HogFunctionWebhookResult | null
    /** What a source webhook or log transformation hands on: captured events, its response, or the transformed record. */
    deliveredOutput: string[]
    sensitiveValues: string[]
    integrationCredentials: string[]
}

const EXECUTION_BUDGET_MS = 5000
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
        private team: Team,
        private executor: HogExecutorAsyncService,
        private hogInputsService: HogInputsService,
        private transformer: HogTransformerService,
        private sourceWebhooks: CdpSourceWebhooksConsumer,
        private hogFunctionManager: HogFunctionManagerService
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
        const executor = new HogExecutorAsyncService(
            new HogExecutorService({ executionTimeoutMs: EXECUTION_BUDGET_MS }, hogInputsService),
            {
                googleAdwordsDeveloperToken: 'fake-developer-token',
                fetchRetries: 3,
                fetchBackoffBaseMs: 100,
                fetchBackoffMaxMs: 1000,
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
                pushNotificationService: undefined as any,
            }
        )
        const transformer = createHogTransformerService(
            { ...hub, TRANSFORMATIONS_HOG_TIMEOUT_MS: EXECUTION_BUDGET_MS, CDP_HOG_RUST_VM_EXECUTION_ENABLED: false },
            { ...hub, monitoringOutputs: createTestMonitoringOutputs(undefined as unknown as KafkaProducerWrapper) }
        )
        const sourceWebhooks = new CdpSourceWebhooksConsumer(
            { ...hub, CDP_WATCHER_HOG_COST_TIMING_UPPER_MS: EXECUTION_BUDGET_MS },
            createCdpConsumerDeps(hub),
            { hogQueue: createMockJobQueue(), hogflowQueue: createMockJobQueue() }
        )
        const hogFunctionManager = new HogFunctionManagerService(hub.postgres, hub.pubSub, hub.encryptedFields)
        const pipeline = new TemplatePipeline(
            hub,
            team,
            executor,
            hogInputsService,
            transformer,
            sourceWebhooks,
            hogFunctionManager
        )
        pipeline.interceptNetwork()
        return pipeline
    }

    async stop(): Promise<void> {
        jest.restoreAllMocks()
        await this.sourceWebhooks.stop()
        await closeHub(this.hub)
    }

    async run(templateCase: TemplateCase, response: ResponseScenario, options: RunOptions = {}): Promise<PipelineRun> {
        this.requests = []
        this.response = response

        const { hogFunction, integrationCredentials } = await this.createHogFunction(templateCase, options)
        const globals = this.representativeGlobals(templateCase)
        const sensitiveValues = [...this.sensitiveInputValues(hogFunction), ...integrationCredentials]

        if (hogFunction.type === 'source_webhook') {
            return await this.runSourceWebhook(hogFunction, sensitiveValues, options)
        }

        if (hogFunction.type === 'transformation_log') {
            return await this.runLogTransformation(hogFunction, sensitiveValues)
        }

        if (hogFunction.type === 'transformation') {
            const { invocationResults } = await this.transformer.transformEvent(pluginEventFrom(globals), [hogFunction])
            const result = invocationResults[0]
            return {
                invocationErrors: result ? [] : ['the transformation did not run'],
                result,
                requests: this.requests,
                printedOutput: result?.logs.map((log) => log.message) ?? [],
                deliveredOutput: [],
                sensitiveValues,
                integrationCredentials,
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
            deliveredOutput: [],
            sensitiveValues,
            integrationCredentials,
        }
    }

    private async runSourceWebhook(
        hogFunction: HogFunctionType,
        sensitiveValues: string[],
        options: RunOptions
    ): Promise<PipelineRun> {
        const configuredSecrets = Object.fromEntries(
            Object.entries(hogFunction.encrypted_inputs ?? {}).map(([key, input]) => [key, String(input.value)])
        )
        const credentials = options.forgedCredentials
            ? Object.fromEntries(Object.keys(configuredSecrets).map((key) => [key, `fake-forged-${key}-0000`]))
            : configuredSecrets
        const request = representativeWebhookRequest(hogFunction.template_id ?? '', credentials)

        const result = await this.sourceWebhooks.executeHogFunction(request, hogFunction, null)
        const httpResponse = getCustomHttpResponse(result)

        return {
            invocationErrors: [],
            result,
            httpResponse,
            requests: this.requests,
            printedOutput: result.logs.map((log) => log.message),
            deliveredOutput: [JSON.stringify(result.capturedPostHogEvents), JSON.stringify(httpResponse?.body ?? '')],
            sensitiveValues,
            integrationCredentials: [],
        }
    }

    private async runLogTransformation(hogFunction: HogFunctionType, sensitiveValues: string[]): Promise<PipelineRun> {
        const monitoring = new HogFunctionMonitoringService(
            createTestMonitoringOutputs(undefined as unknown as KafkaProducerWrapper)
        )
        const transformer = new LogsTransformerService(this.hogFunctionManager, monitoring, {
            siteUrl: this.hub.SITE_URL,
            hogTimeoutMs: EXECUTION_BUDGET_MS,
            messageBudgetMs: EXECUTION_BUDGET_MS,
            batchBudgetMs: EXECUTION_BUDGET_MS,
            maxErrorLogsPerFunctionPerMessage: 1,
        })
        const records = [representativeLogRecord()]

        await transformer.transformRecordsWith(this.team.id, [hogFunction], records)

        const logs = monitoring.queuedLogMessages
        const failed = records.some((record) => record.attributes?.[ATTR_TRANSFORMATIONS_FAILED])
        return {
            invocationErrors: [
                ...logs.filter((log) => log.level === 'error').map((log) => log.message),
                ...(failed ? ['the record is marked as failed'] : []),
            ],
            requests: this.requests,
            printedOutput: logs.map((log) => log.message),
            deliveredOutput: records.map((record) => JSON.stringify(record)),
            sensitiveValues,
            integrationCredentials: [],
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
    ): Promise<{ hogFunction: HogFunctionType; integrationCredentials: string[] }> {
        const { template, mapping } = templateCase
        const integrationCredentials: string[] = []
        const values: Record<string, unknown> = {}

        for (const schema of template.inputs_schema) {
            if (schema.type === 'integration') {
                const credentials = fakeIntegrationCredentials(schema.key)
                integrationCredentials.push(...Object.values(credentials))
                values[schema.key] = await this.insertIntegration(schema, credentials)
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

        return { hogFunction, integrationCredentials }
    }

    private async insertIntegration(
        schema: HogFunctionInputSchemaType,
        credentials: Record<string, string>
    ): Promise<number> {
        const integration = await insertIntegration(this.hub.postgres, this.team.id, {
            kind: schema.integration as any,
            config: INTEGRATION_CONFIGS[schema.integration ?? ''] ?? {},
            sensitive_config: Object.fromEntries(
                Object.entries(credentials).map(([key, value]) => [key, this.hub.encryptedFields.encrypt(value)])
            ),
        })
        return integration.id
    }

    private sensitiveInputValues(hogFunction: HogFunctionType): string[] {
        return Object.values(hogFunction.encrypted_inputs ?? {})
            .map((input) => input.value)
            .filter((value): value is string => typeof value === 'string')
    }

    private representativeGlobals(templateCase: TemplateCase): HogFunctionInvocationGlobals {
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

const representativeLogRecord = (): LogRecord => ({
    uuid: '01920000-0000-7000-8000-000000000005',
    trace_id: null,
    span_id: null,
    trace_flags: 0,
    timestamp: 1_735_689_600_000_000_000,
    observed_timestamp: 1_735_689_600_000_000_000,
    body: 'user ada@example.com signed in from 203.0.113.10',
    severity_text: 'info',
    severity_number: 9,
    service_name: 'example-api',
    resource_attributes: { 'service.namespace': encodeLogAttributeValue('example') },
    instrumentation_scope: 'example.sessions',
    event_name: null,
    attributes: {
        'user.email': encodeLogAttributeValue('ada@example.com'),
        'user.id': encodeLogAttributeValue('example-user-id'),
        'http.method': encodeLogAttributeValue('POST'),
    },
    bytes_uncompressed: 120,
})

type ProviderRequest = {
    body: Record<string, unknown>
    /** Headers the provider derives from a secret it shares with the source, such as a body signature. */
    signedHeaders?: (credentials: Record<string, string>, rawBody: string) => Record<string, string>
}

const SIGNATURE_TIMESTAMP = '1735689600'

// A source template parses its own provider's payload, so each provider gets a request of its own shape.
const PROVIDER_REQUESTS: Record<string, ProviderRequest> = {
    'template-source-stripe-webhook': {
        body: {
            type: 'customer.created',
            data: { object: { object: 'customer', id: 'cus_example0000', customer: 'cus_example0000' } },
        },
        signedHeaders: (credentials, rawBody) => ({
            'stripe-signature': `t=${SIGNATURE_TIMESTAMP},v1=${createHmac('sha256', credentials.signing_secret ?? '')
                .update(`${SIGNATURE_TIMESTAMP}.${rawBody}`)
                .digest('hex')}`,
        }),
    },
    'template-source-vercel-log-drain': {
        body: {
            id: 'log-example-0001',
            deploymentId: 'dpl_example0000',
            projectId: 'prj_example0000',
            projectName: 'example-app',
            source: 'request',
            environment: 'production',
            level: 'info',
            message: 'GET /pricing 200',
            timestamp: 1735689600000,
            host: 'example.com',
            path: '/pricing?utm_source=newsletter',
            statusCode: 200,
            proxy: {
                timestamp: 1735689600000,
                method: 'GET',
                host: 'example.com',
                path: '/pricing?utm_source=newsletter',
                userAgent: ['Mozilla/5.0 (Macintosh)'],
                clientIp: '203.0.113.10',
                scheme: 'https',
                statusCode: 200,
            },
        },
    },
}

const GENERIC_WEBHOOK_REQUEST: ProviderRequest = {
    body: { event: 'order_completed', distinct_id: 'example-distinct-id' },
}

const representativeWebhookRequest = (
    templateId: string,
    credentials: Record<string, string>
): SourceWebhookRequest => {
    const { body, signedHeaders } = PROVIDER_REQUESTS[templateId] ?? GENERIC_WEBHOOK_REQUEST
    const rawBody = JSON.stringify(body)
    return {
        method: 'POST',
        headers: {
            'content-type': 'application/json',
            'user-agent': 'example-provider/1.0',
            ...(credentials.auth_header ? { authorization: credentials.auth_header } : {}),
            ...signedHeaders?.(credentials, rawBody),
        },
        body,
        rawBody,
        query: { ph_event: 'email_opened', ph_distinct_id: 'example-distinct-id' },
        ip: '203.0.113.10',
        socket: { remoteAddress: '203.0.113.10' },
    }
}

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
