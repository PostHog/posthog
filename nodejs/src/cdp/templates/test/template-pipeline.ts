import { readFileSync } from 'fs'
import path from 'path'

import { CyclotronInputType } from '~/cdp/schema/cyclotron'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { parseJSON } from '~/common/utils/json-parse'
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
    CyclotronJobInvocation,
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    GroupType,
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
import { KafkaQueueHandoff } from './kafka-queue-handoff'

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
    entry?: CorpusEntry
}

/** One event with the person and groups it belongs to. Plain JSON, so a recorded corpus can replace the invented one. */
export type CorpusEntry = {
    name: string
    event: Omit<HogFunctionInvocationGlobals['event'], 'url'>
    person?: Omit<NonNullable<HogFunctionInvocationGlobals['person']>, 'url'>
    groups?: Record<string, Omit<GroupType, 'url'>>
}

export const INVENTED_CORPUS_PATH = path.join(__dirname, 'corpus', 'invented-events.json')

export const loadCorpus = (corpusPath: string): CorpusEntry[] => parseJSON(readFileSync(corpusPath, 'utf-8'))

const INVENTED_CORPUS = loadCorpus(INVENTED_CORPUS_PATH)

export type PipelineRun = {
    invocationErrors: string[]
    result?: CyclotronJobInvocationResult
    /** A throw rejects the whole batch in production, so it is never a visible failure of one invocation. */
    thrown?: string
    requests: OutgoingRequest[]
    printedOutput: string[]
    /** Secret inputs by key, and integration credentials by `<input key>.<credential>`. */
    secrets: Record<string, string>
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

export type QueuedJob = {
    teamId: number
    /** Stands in for the stored function row, which the worker loads by id. */
    hogFunction: HogFunctionType
    /** Stand in for the groups and person the worker loads again when the queue strips them. */
    groups: HogFunctionInvocationGlobals['groups']
    person: HogFunctionInvocationGlobals['person']
    secrets: Record<string, string>
    integrationCredentials: string[]
    buildErrors: string[]
    messages: string[]
}

const loadedByWorker = (
    invocation: CyclotronJobInvocation,
    job: QueuedJob
): CyclotronJobInvocationHogFunction | string => {
    if (invocation.functionId !== job.hogFunction.id) {
        return `the worker found no function with id ${invocation.functionId}`
    }
    const state = invocation.state as CyclotronJobInvocationHogFunction['state'] | null
    if (!state) {
        return 'the worker cannot read a job with no state'
    }
    if (!state.globals?.project || !state.globals.event) {
        return 'the worker skipped the job, because its globals have no project or event'
    }
    const globals = {
        ...state.globals,
        groups: state.globals.groups ?? job.groups,
        person: state.globals.person ?? job.person,
    }
    return { ...invocation, state: { ...state, globals }, hogFunction: job.hogFunction }
}

export class TemplatePipeline {
    private requests: OutgoingRequest[] = []
    private response: ResponseScenario = { status: 200, body: {} }
    private handoff?: KafkaQueueHandoff

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

    get teamId(): number {
        return this.team.id
    }

    async stop(): Promise<void> {
        jest.restoreAllMocks()
        await closeHub(this.hub)
    }

    async run(templateCase: TemplateCase, response: ResponseScenario, options: RunOptions = {}): Promise<PipelineRun> {
        this.requests = []
        this.response = response

        const { hogFunction, globals, secrets, integrationCredentials } = await this.prepare(templateCase, options)
        const evidence = {
            requests: this.requests,
            secrets,
            sensitiveValues: Object.values(secrets),
            integrationCredentials,
        }

        if (hogFunction.type === 'transformation') {
            const { invocationResults } = await this.transformer.transformEvent(pluginEventFrom(globals), [hogFunction])
            const result = invocationResults[0]
            return {
                invocationErrors: result ? [] : ['the transformation did not run'],
                result,
                printedOutput: result?.logs.map((log) => log.message) ?? [],
                ...evidence,
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
        const { result, thrown } =
            invocations.length === 1
                ? await this.execute(invocations[0], { maxAsyncFunctions: MAX_ASYNC_FUNCTIONS })
                : {}

        return {
            invocationErrors,
            result,
            thrown,
            printedOutput: result?.logs.map((log) => log.message) ?? [],
            ...evidence,
        }
    }

    async queueJob(templateCase: TemplateCase, entry: CorpusEntry): Promise<QueuedJob> {
        const { hogFunction, globals, secrets, integrationCredentials } = await this.prepare(templateCase, { entry })
        const { invocations, buildFailures } = await buildHogFunctionInvocations(
            this.hogInputsService,
            [hogFunction],
            globals
        )
        const buildErrors = buildFailures.map((failure) => `${failure.step}: ${failure.error}`)
        if (invocations.length !== 1) {
            buildErrors.push(`expected 1 invocation, got ${invocations.length}`)
        }
        const messages = await (await this.kafkaHandoff()).queue(invocations)

        return {
            teamId: this.team.id,
            hogFunction,
            groups: globals.groups,
            person: globals.person,
            secrets,
            integrationCredentials,
            buildErrors,
            messages: messages.map((message) => message.toString('base64')),
        }
    }

    async runQueuedJob(job: QueuedJob, response: ResponseScenario): Promise<PipelineRun> {
        this.requests = []
        this.response = response
        const handoff = await this.kafkaHandoff()
        const invocationErrors = [...job.buildErrors]
        const printedOutput: string[] = []
        let messages: Buffer[] = job.messages.map((message) => Buffer.from(message, 'base64'))
        let execution: { result?: CyclotronJobInvocationResult; thrown?: string } = {}

        for (let pickup = 1; messages.length > 0; pickup++) {
            if (pickup > MAX_ASYNC_FUNCTIONS) {
                invocationErrors.push(`still queued after ${MAX_ASYNC_FUNCTIONS} pickups`)
                break
            }
            const invocations = await handoff.consume(messages).catch((error) => {
                invocationErrors.push(`consuming the queued job threw: ${String(error)}`)
                return null
            })
            if (!invocations) {
                break
            }
            if (invocations.length !== 1) {
                invocationErrors.push(`expected 1 queued invocation, got ${invocations.length}`)
                break
            }
            const loaded = loadedByWorker(invocations[0], job)
            if (typeof loaded === 'string') {
                invocationErrors.push(loaded)
                break
            }
            // The worker passes no options, so each pickup runs at most one queued async function.
            execution = await this.execute(loaded)
            if (!execution.result) {
                break
            }
            printedOutput.push(...execution.result.logs.map((log) => log.message))
            messages = await handoff.requeue([execution.result])
        }

        return {
            invocationErrors,
            ...execution,
            printedOutput,
            requests: this.requests,
            secrets: job.secrets,
            sensitiveValues: Object.values(job.secrets),
            integrationCredentials: job.integrationCredentials,
        }
    }

    private async prepare(
        templateCase: TemplateCase,
        options: RunOptions
    ): Promise<{
        hogFunction: HogFunctionType
        globals: HogFunctionInvocationGlobals
        secrets: Record<string, string>
        integrationCredentials: string[]
    }> {
        const { hogFunction, integrationSecrets } = await this.createHogFunction(templateCase, options)
        return {
            hogFunction,
            globals: this.globalsFor(templateCase, options.entry ?? INVENTED_CORPUS[0]),
            secrets: { ...secretInputs(hogFunction), ...integrationSecrets },
            integrationCredentials: Object.values(integrationSecrets),
        }
    }

    private async kafkaHandoff(): Promise<KafkaQueueHandoff> {
        this.handoff ??= await KafkaQueueHandoff.start(this.hub)
        return this.handoff
    }

    private async execute(
        invocation: CyclotronJobInvocationHogFunction,
        options?: { maxAsyncFunctions: number }
    ): Promise<{ result?: CyclotronJobInvocationResult; thrown?: string }> {
        try {
            return { result: await this.executor.executeWithAsyncFunctions(invocation, options) }
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
    ): Promise<{ hogFunction: HogFunctionType; integrationSecrets: Record<string, string> }> {
        const { template, mapping } = templateCase
        const integrationSecrets: Record<string, string> = {}
        const values: Record<string, unknown> = {}

        for (const schema of template.inputs_schema) {
            if (schema.type === 'integration') {
                const credentials = fakeIntegrationCredentials(schema.key)
                for (const [name, credential] of Object.entries(credentials)) {
                    integrationSecrets[`${schema.key}.${name}`] = credential
                }
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

        return { hogFunction, integrationSecrets }
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

    private globalsFor(templateCase: TemplateCase, entry: CorpusEntry): HogFunctionInvocationGlobals {
        const projectUrl = `https://us.posthog.com/project/${this.team.id}`
        const eventName = eventNameFor(templateCase, entry)
        return {
            project: { id: this.team.id, name: 'Example project', url: projectUrl },
            event: {
                ...entry.event,
                event: eventName,
                url: `${projectUrl}/events/${entry.event.uuid}`,
                properties: { ...SYSTEM_EVENT_PROPERTIES[eventName], ...entry.event.properties },
            },
            person: entry.person && {
                ...entry.person,
                url: `${projectUrl}/person/${entry.event.distinct_id}`,
            },
            groups: Object.fromEntries(
                Object.entries(entry.groups ?? {}).map(([key, group]) => [
                    key,
                    { ...group, url: `${projectUrl}/groups/${group.index}/${group.id}` },
                ])
            ),
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

const secretInputs = (hogFunction: HogFunctionType): Record<string, string> =>
    Object.fromEntries(
        Object.entries(hogFunction.encrypted_inputs ?? {})
            .map(([key, input]) => [key, input.value] as const)
            .filter((entry): entry is readonly [string, string] => typeof entry[1] === 'string')
    )

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
const eventNameFor = ({ mapping }: TemplateCase, entry: CorpusEntry): string => {
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
    return entry.event.event
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
