import { SESv2Client } from '@aws-sdk/client-sesv2'
import type { NodeHttpHandler } from '@smithy/node-http-handler'
import { Resolver } from 'node:dns/promises'
import { Readable } from 'node:stream'

import { CyclotronInputType } from '~/cdp/schema/cyclotron'
import { HogFlowAction } from '~/cdp/schema/hogflow'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { closeHub, createHub } from '~/common/utils/db/hub'
import * as requestModule from '~/common/utils/request'
import { FetchOptions, FetchResponse } from '~/common/utils/request'
import { PluginEvent } from '~/plugin-scaffold'
import { createTestMonitoringOutputs } from '~/tests/helpers/ingestion-outputs'
import { createTestTeamFixture } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'

import { FixtureHogFlowBuilder, SimpleHogFlowRepresentation } from '../../_tests/builders/hogflow.builder'
import { insertHogFunctionTemplate, insertIntegration } from '../../_tests/fixtures'
import { HogTransformerService, createHogTransformerService } from '../../hog-transformations/hog-transformer.service'
import { PostgresCohortMembershipRepository } from '../../services/cohorts/postgres-cohort-membership-repository'
import { HogExecutorAsyncService } from '../../services/hog-executor-async.service'
import { HogExecutorService } from '../../services/hog-executor.service'
import { HogInputsService } from '../../services/hog-inputs.service'
import { HogFlowExecutorService } from '../../services/hogflows/hogflow-executor.service'
import { HogFlowFunctionsService } from '../../services/hogflows/hogflow-functions.service'
import { HogFunctionTemplateManagerService } from '../../services/managers/hog-function-template-manager.service'
import { RecipientsManagerService } from '../../services/managers/recipients-manager.service'
import { TeamWorkflowsConfigService } from '../../services/managers/team-workflows-config.service'
import {
    EmailSuppressionService,
    emailSuppressionConfigFromEnv,
} from '../../services/messaging/email-suppression.service'
import { EmailValidationService } from '../../services/messaging/email-validation.service'
import { EmailService } from '../../services/messaging/email.service'
import { EmailTrackingCodeSigner } from '../../services/messaging/helpers/tracking-code'
import { RecipientPreferencesService } from '../../services/messaging/recipient-preferences.service'
import { RecipientTokensService } from '../../services/messaging/recipient-tokens.service'
import {
    CyclotronJobInvocation,
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationResult,
    HogFunctionInputSchemaType,
    HogFunctionInvocationGlobals,
    HogFunctionMappingTemplate,
    HogFunctionTemplate,
    HogFunctionType,
    InvocationBuildFailure,
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

const PRODUCTION_SITE_URL = 'https://us.posthog.com'
const EXECUTION_BUDGET_MS = 5000
// Django compiles filters to bytecode. The event name already targets the mapping, so matching everything is safe.
const MATCH_ALL_FILTERS = { bytecode: ['_h', 29] }
const MATCH_ALL_TRIGGER = { type: 'event' as const, filters: { events: [], actions: [], ...MATCH_ALL_FILTERS } }
const MAX_ASYNC_FUNCTIONS = 10
const AWAITED_STEPS_PRODUCTION_DEFAULT = false
const FAIL_THE_RUN_ON_STEP_ERROR = 'abort' as const

type WorkflowStepType = Extract<HogFlowAction['type'], 'function' | 'function_email'>

const WORKFLOW_ONLY_STEP_TYPES: Record<string, WorkflowStepType> = {
    'template-email': 'function_email',
    'template-posthog-classify': 'function',
    'template-posthog-create-customer-task': 'function',
    'template-posthog-create-task': 'function',
    'template-posthog-run-scout': 'function',
    'template-posthog-send-ticket-message': 'function',
}

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
        private hogFlowExecutor: HogFlowExecutorService,
        private hogInputsService: HogInputsService,
        private transformer: HogTransformerService
    ) {}

    static async start(): Promise<TemplatePipeline> {
        const hub = await createHub({ SITE_URL: PRODUCTION_SITE_URL })
        const { team } = await createTestTeamFixture(hub.postgres)
        const recipientTokensService = new RecipientTokensService(hub.ENCRYPTION_SALT_KEYS, hub.SITE_URL)
        const recipientsManager = new RecipientsManagerService(hub.postgres)
        const emailSuppressionService = new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv())
        const emailService = new EmailService(
            {
                sesAccessKeyId: hub.SES_ACCESS_KEY_ID,
                sesSecretAccessKey: hub.SES_SECRET_ACCESS_KEY,
                sesRegion: hub.SES_REGION,
                sesEndpoint: hub.SES_ENDPOINT,
                sesTrackedConfigurationSet: hub.SES_TRACKED_CONFIGURATION_SET,
                sesUntrackedConfigurationSet: hub.SES_UNTRACKED_CONFIGURATION_SET,
            },
            hub.integrationManager,
            new TeamWorkflowsConfigService(hub.postgres, hub.pubSub),
            hub.ENCRYPTION_SALT_KEYS,
            hub.SITE_URL,
            new EmailTrackingCodeSigner(hub.ENCRYPTION_SALT_KEYS, hub.CDP_EMAIL_TRACKING_URL),
            emailSuppressionService,
            recipientsManager
        )
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
                emailService,
                recipientTokensService,
                pushNotificationService: undefined as any,
            }
        )
        const hogFlowExecutor = new HogFlowExecutorService(
            new HogFlowFunctionsService(hub.SITE_URL, new HogFunctionTemplateManagerService(hub.postgres), executor),
            new RecipientPreferencesService(recipientsManager, emailSuppressionService),
            new EmailValidationService(null),
            new PostgresCohortMembershipRepository(hub.postgres),
            hub.integrationManager,
            undefined,
            undefined,
            { awaitedStepsEnabled: AWAITED_STEPS_PRODUCTION_DEFAULT }
        )
        const transformer = createHogTransformerService(
            { ...hub, TRANSFORMATIONS_HOG_TIMEOUT_MS: EXECUTION_BUDGET_MS, CDP_HOG_RUST_VM_EXECUTION_ENABLED: false },
            { ...hub, monitoringOutputs: createTestMonitoringOutputs(undefined as unknown as KafkaProducerWrapper) }
        )
        const pipeline = new TemplatePipeline(hub, team, executor, hogFlowExecutor, hogInputsService, transformer)
        pipeline.interceptNetwork()
        emailService.sesV2Client = pipeline.sesClientOverInterceptedNetwork()
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

        const stepType = WORKFLOW_ONLY_STEP_TYPES[templateCase.template.id]
        const { invocationErrors, result, thrown } = stepType
            ? await this.runAsWorkflowStep(templateCase.template, stepType, hogFunction, globals)
            : await this.runAsHogFunction(hogFunction, globals)

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

    private async runAsHogFunction(
        hogFunction: HogFunctionType,
        globals: HogFunctionInvocationGlobals
    ): Promise<Execution> {
        const { invocations, buildFailures } = await buildHogFunctionInvocations(
            this.hogInputsService,
            [hogFunction],
            globals
        )
        return await this.executeSingle(invocations, buildFailures, (invocation) =>
            this.executor.executeWithAsyncFunctions(invocation, { maxAsyncFunctions: MAX_ASYNC_FUNCTIONS })
        )
    }

    private async runAsWorkflowStep(
        template: HogFunctionTemplate,
        stepType: WorkflowStepType,
        hogFunction: HogFunctionType,
        globals: HogFunctionInvocationGlobals
    ): Promise<Execution> {
        const hogFlow = new FixtureHogFlowBuilder()
            .withTeamId(this.team.id)
            .withWorkflow({
                actions: {
                    trigger: { type: 'trigger', config: MATCH_ALL_TRIGGER },
                    step: {
                        type: stepType,
                        on_error: FAIL_THE_RUN_ON_STEP_ERROR,
                        config: {
                            template_id: await this.registerTemplateUnderTeamScopedId(template),
                            inputs: { ...hogFunction.inputs, ...hogFunction.encrypted_inputs },
                        },
                    } as SimpleHogFlowAction,
                    exit: { type: 'exit', config: {} },
                },
                edges: [
                    { from: 'trigger', to: 'step', type: 'continue' },
                    { from: 'step', to: 'exit', type: 'continue' },
                ],
            })
            .build()
        const { invocations, buildFailures } = await this.hogFlowExecutor.buildHogFlowInvocations([hogFlow], globals)
        return await this.executeSingle(invocations, buildFailures, (invocation) =>
            this.executeHogFlowAcrossQueueSwitches(invocation)
        )
    }

    private async executeHogFlowAcrossQueueSwitches(
        invocation: CyclotronJobInvocationHogFlow
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>> {
        const logs: CyclotronJobInvocationResult['logs'] = []
        let result = await this.hogFlowExecutor.execute(invocation)
        logs.push(...result.logs)
        while (!result.finished && result.invocation.state.currentAction?.routingOnlyReschedule) {
            result = await this.hogFlowExecutor.execute(result.invocation)
            logs.push(...result.logs)
        }
        return { ...result, logs }
    }

    private async registerTemplateUnderTeamScopedId(template: HogFunctionTemplate): Promise<string> {
        const { template_id } = await insertHogFunctionTemplate(this.hub.postgres, {
            ...template,
            id: `${template.id}-contract-${this.team.id}`,
        })
        return template_id
    }

    private async executeSingle<T extends CyclotronJobInvocation>(
        invocations: T[],
        buildFailures: InvocationBuildFailure[],
        execute: (invocation: T) => Promise<CyclotronJobInvocationResult<T>>
    ): Promise<Execution> {
        const invocationErrors = buildFailures.map((failure) => `${failure.step}: ${failure.error}`)
        if (invocations.length !== 1) {
            invocationErrors.push(`expected 1 invocation, got ${invocations.length}`)
            return { invocationErrors }
        }
        try {
            return { invocationErrors, result: await execute(invocations[0]) }
        } catch (error) {
            return { invocationErrors, thrown: `execution threw: ${String(error)}` }
        }
    }

    private interceptNetwork(): void {
        const respond = (url: string, options: FetchOptions = {}): Promise<FetchResponse> => {
            const { status, body } = this.record({
                url,
                method: options.method ?? 'GET',
                headers: (options.headers as Record<string, string>) ?? {},
                body: typeof options.body === 'string' ? options.body : undefined,
            })
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
        jest.spyOn(Resolver.prototype, 'resolveMx').mockResolvedValue([{ exchange: 'mx.example.com', priority: 10 }])
    }

    private record(request: OutgoingRequest): { status: number; body: unknown } {
        this.requests.push(request)
        const { status, echoRequest } = this.response
        return { status, body: echoRequest ? { error: 'Request rejected', request } : this.response.body }
    }

    private sesClientOverInterceptedNetwork(): SESv2Client {
        return new SESv2Client({
            region: this.hub.SES_REGION,
            endpoint: this.hub.SES_ENDPOINT,
            credentials: { accessKeyId: 'fake-ses-access-key-id', secretAccessKey: 'fake-ses-secret-access-key' },
            requestHandler: {
                handle: (request: SesHttpRequest) => {
                    const { status, body } = this.record({
                        url: urlOf(request),
                        method: request.method,
                        headers: request.headers,
                        body: typeof request.body === 'string' ? request.body : undefined,
                    })
                    const responseBody = status < 300 ? { MessageId: 'example-message-id' } : body
                    return Promise.resolve({
                        response: {
                            statusCode: status,
                            headers: { 'content-type': 'application/json' },
                            body: Readable.from([Buffer.from(JSON.stringify(responseBody))]),
                        },
                    })
                },
            },
        })
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
            } else if (schema.type === 'native_email') {
                values[schema.key] = { ...EMAIL_MESSAGE, from: { integrationId: await this.insertEmailSender() } }
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

    private async insertEmailSender(): Promise<number> {
        const integration = await insertIntegration(this.hub.postgres, this.team.id, {
            kind: 'email',
            config: {
                email: 'orders@example.com',
                name: 'Example Shop',
                domain: 'example.com',
                verified: true,
                provider: 'ses',
            },
        })
        return integration.id
    }

    private sensitiveInputValues(hogFunction: HogFunctionType): string[] {
        return Object.values(hogFunction.encrypted_inputs ?? {})
            .map((input) => input.value)
            .filter((value): value is string => typeof value === 'string')
    }

    private representativeGlobals(templateCase: TemplateCase): HogFunctionInvocationGlobals {
        const projectUrl = `${PRODUCTION_SITE_URL}/project/${this.team.id}`
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

type SesHttpRequest = Parameters<NodeHttpHandler['handle']>[0]
type Execution = Pick<PipelineRun, 'invocationErrors' | 'result' | 'thrown'>
type SimpleHogFlowAction = SimpleHogFlowRepresentation['actions'][string]

const EMAIL_MESSAGE = {
    to: { email: '{{ person.properties.email }}', name: '{{ person.properties.name }}' },
    replyTo: '',
    cc: '',
    bcc: '',
    subject: 'Your order {{ event.properties.order_id }} is confirmed',
    preheader: '',
    text: 'Hi {{ person.properties.first_name }}, thanks for your order.',
    html: '<p>Hi {{ person.properties.first_name }}, thanks for your order.</p>',
}

// The non-secret part of a connection that templates read, keyed by integration kind.
const INTEGRATION_CONFIGS: Record<string, Record<string, unknown>> = {
    github: { account: { name: 'example-org' } },
    gitlab: { hostname: 'https://gitlab.example.com', project_id: 1001 },
    slack: { scope: 'chat:write,chat:write.customize', team: { id: 'T0000EXAMPLE', name: 'Example workspace' } },
    twilio: { account_sid: 'ACexample0000' },
}

const urlOf = (request: SesHttpRequest): string => {
    const url = new URL(`${request.protocol}//${request.hostname}${request.path}`)
    url.port = request.port ? String(request.port) : ''
    Object.entries(request.query ?? {}).forEach(([key, value]) => url.searchParams.append(key, String(value)))
    return url.href
}

const pluginEventFrom = (globals: HogFunctionInvocationGlobals): PluginEvent => ({
    uuid: globals.event.uuid,
    event: globals.event.event,
    distinct_id: globals.event.distinct_id,
    properties: { ...globals.event.properties },
    timestamp: globals.event.timestamp,
    ip: String(globals.event.properties.$ip),
    site_url: PRODUCTION_SITE_URL,
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
