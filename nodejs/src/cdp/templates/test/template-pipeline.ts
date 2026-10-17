import { CyclotronInputType } from '~/cdp/schema/cyclotron'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { closeHub, createHub } from '~/common/utils/db/hub'
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
import { RecipientTokensService } from '../../services/messaging/recipient-tokens.service'
import {
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    HogFunctionFilters,
    HogFunctionInputSchemaType,
    HogFunctionInvocationGlobals,
    HogFunctionMappingTemplate,
    HogFunctionTemplate,
    HogFunctionType,
} from '../../types'
import { convertToHogFunctionFilterGlobal, filterFunctionInstrumented } from '../../utils/hog-function-filtering'
import { buildHogFunctionInvocations } from '../../utils/invocation-utils'
import { PosthogJwtAudience } from '../../utils/jwt-utils'
import { ScopedServiceJwt } from '../../utils/scoped-service-jwt'
import { compileHog, compileHogFilters, compileHogTemplate } from '../compiler'

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

export type FilterMatch = {
    scope: 'function' | 'mapping'
    match: boolean
    error?: string
}

export type PipelineRun = {
    invocationErrors: string[]
    result?: CyclotronJobInvocationResult
    /** A throw rejects the whole batch in production, so it is never a visible failure of one invocation. */
    thrown?: string
    requests: OutgoingRequest[]
    printedOutput: string[]
    sensitiveValues: string[]
    integrationCredentials: string[]
}

const EXECUTION_BUDGET_MS = 5000
// The real filters have their own invariant, so the other invariants run whether or not the event passes them.
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
        const pipeline = new TemplatePipeline(hub, team, executor, hogInputsService, transformer)
        pipeline.interceptNetwork()
        return pipeline
    }

    async stop(): Promise<void> {
        jest.restoreAllMocks()
        await closeHub(this.hub)
    }

    async run(templateCase: TemplateCase, response: ResponseScenario, options: RunOptions = {}): Promise<PipelineRun> {
        this.requests = []
        this.response = response

        const { hogFunction, integrationCredentials } = await this.createHogFunction(templateCase, options)
        const globals = this.representativeGlobals(templateCase)
        const sensitiveValues = [...this.sensitiveInputValues(hogFunction), ...integrationCredentials]

        if (hogFunction.type === 'transformation') {
            const { invocationResults } = await this.transformer.transformEvent(pluginEventFrom(globals), [hogFunction])
            const result = invocationResults[0]
            return {
                invocationErrors: result ? [] : ['the transformation did not run'],
                result,
                requests: this.requests,
                printedOutput: result?.logs.map((log) => log.message) ?? [],
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
            sensitiveValues,
            integrationCredentials,
        }
    }

    async matchRealFilters(templateCase: TemplateCase): Promise<FilterMatch[]> {
        const { hogFunction } = await this.createHogFunction(templateCase, {})
        const globals = this.representativeGlobals(templateCase)
        // Ingestion runs transformations before the event has a person or groups.
        const filterGlobals = convertToHogFunctionFilterGlobal(
            hogFunction.type === 'transformation' ? { event: globals.event } : globals
        )
        const scopes: [FilterMatch['scope'], HogFunctionFilters | null | undefined][] = [
            ['function', functionFilters(templateCase.template)],
        ]
        if (templateCase.mapping) {
            scopes.push(['mapping', templateCase.mapping.filters])
        }
        return await Promise.all(
            scopes.map(async ([scope, filters]): Promise<FilterMatch> => {
                const compiled = filters ? await compileHogFilters(filters, hogFunction.type) : filters
                const result = await filterFunctionInstrumented({
                    fn: hogFunction,
                    filters: compiled,
                    filterGlobals,
                    caller: hogFunction.type === 'transformation' ? 'transformation' : 'build_hog_function_invocations',
                })
                const error =
                    compiled?.bytecode_error ?? (result.error === undefined ? undefined : String(result.error))
                return { scope, match: result.match, ...(error === undefined ? {} : { error }) }
            })
        )
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

// The editor drops event and action filters from a function with mappings, so only its mappings pick events.
const functionFilters = ({ filters = {}, mapping_templates }: HogFunctionTemplate): HogFunctionFilters => {
    if (!mapping_templates) {
        return filters
    }
    const { events: _events, actions: _actions, ...rest } = filters
    return rest
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

// Filters name their event either as the event id or in a HogQL property such as `event in ('$pageview')`.
const eventNameFor = ({ template, mapping }: TemplateCase): string => {
    const firstEvent = (mapping ? mapping.filters : template.filters)?.events?.[0]
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
