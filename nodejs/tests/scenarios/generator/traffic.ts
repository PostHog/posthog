import type Chance from 'chance'
import { createHash } from 'crypto'
import { setTimeout as sleep } from 'timers/promises'
import { z } from 'zod'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { createIncomingEvent } from '~/cdp/_tests/fixtures'
import { CyclotronInputType, MAX_EMAIL_ATTACHMENTS } from '~/cdp/schema/cyclotron'
import { HogFlow } from '~/cdp/schema/hogflow'
import { ATTACHMENT_UPLOAD_TOKEN_CLAIMS, CODE_SEND_TOKEN_CLAIMS } from '~/cdp/services/hogflows/transactional-email'
import { MESSAGE_MAX_BYTES, estimateMessageBytes } from '~/cdp/services/messaging/message-estimate'
import { compileHog } from '~/cdp/templates/compiler'
import type { ScopedServiceJwt } from '~/cdp/utils/scoped-service-jwt'
import type { KafkaProducerWrapper } from '~/common/kafka/producer'
import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'

import type { TrafficDefinition } from '../cards/definitions'
import { Duration, durationMs } from '../duration'
import type { FollowUpAnswer, IntakeAnswer, JournalEntry } from '../judge/judge'
import { UNIT_EMAIL_DOMAIN, WEBHOOK_HOST } from '../provider-edge'
import type { SesFeedback } from './ses-feedback'

const Shape = z.object({ ratePerSecond: z.number().positive(), parks: z.number().int().min(0).default(0) }).strict()

export type UnitFile = { seed: number; sizeBytes: number }

export type Unit = { unitId: string; teamId: number; flowId: string; files?: readonly UnitFile[] }

export type OfferAnswer = JournalEntry['answer'] & { attachments?: readonly string[] }

export type Burst = { fromMs: number; forMs: number; scale: number }

export type Emit = (unit: Unit, event: string, properties: object) => Promise<IntakeAnswer>

export type SendClock = { now(): number; wait(ms: number, signal: AbortSignal): Promise<void> }

export type OfferContext = {
    emit: Emit
    cdpApi?: { nextUrl: () => string; jwt: Pick<ScopedServiceJwt, 'mint'>; clock?: SendClock }
    sesFeedback?: SesFeedback
}

export type UnitLoad = { claims: { hogflow: number; email: number }; newJobs: number }

export type TrafficKind = Omit<TrafficDefinition, 'profile'> & {
    profile: z.ZodType<z.infer<typeof Shape>>
    intake: JournalEntry['kind']
    deliveries: string[]
    needsLocal?: true
    unitLoad?(parks: number): UnitLoad
    flow(teamId: number, emailIntegrationId: number, parks: number): Promise<HogFlow>
    offer(unit: Unit, context: OfferContext, signal: AbortSignal): Promise<OfferAnswer>
    burstOf?(params: unknown): Burst | undefined
    filesOf?(chance: Chance.Chance, profile: unknown, atLimit: boolean): UnitFile[]
    followUp?: {
        flow(teamId: number, emailIntegrationId: number, parks: number): Promise<HogFlow>
        offer(unit: Unit, context: OfferContext, signal: AbortSignal): Promise<FollowUpAnswer>
    }
}

export const SENDER = { email: 'flows@www.example.com', name: 'Scenario runner', domain: 'www.example.com' }

export const EMAIL_ACTION = 'email'
export const WEBHOOK_ACTION = 'webhook'

const unitAddress = (unit: Unit): string => `${unit.unitId}@${UNIT_EMAIL_DOMAIN}`

const eventTrigger = (event: string): object => ({
    type: 'event',
    filters: {
        events: [{ id: event, name: event, type: 'events', order: 0 }],
        actions: [],
        bytecode: ['_H', 1, 32, event, 32, 'event', 1, 1, 11],
    },
})

const BODY = { subject: 'Scenario delivery', text: 'Scenario delivery', html: '<p>Scenario delivery</p>' }

async function emailInput(emailIntegrationId: number, recipient: string): Promise<CyclotronInputType> {
    const message = (to: unknown): Record<string, unknown> => ({
        to: { email: to, name: '' },
        from: { integrationId: emailIntegrationId, email: SENDER.email },
        ...BODY,
    })
    return {
        templating: 'hog',
        value: message(`{${recipient}}`),
        bytecode: message(await compileHog(`return ${recipient}`)),
    }
}

const emailStep = async (emailIntegrationId: number, recipient: string, config: object = {}): Promise<object> => ({
    type: 'function_email',
    config: {
        template_id: 'template-email',
        inputs: { email: await emailInput(emailIntegrationId, recipient) },
        ...config,
    },
})

const webhookStep = async (): Promise<object> => {
    const url = `https://${WEBHOOK_HOST}/u/{event.properties.unit_id}/${WEBHOOK_ACTION}`
    return {
        type: 'function',
        config: {
            template_id: 'template-webhook',
            inputs: {
                url: { templating: 'hog', value: url, bytecode: await compileHog(`return f'${url}'`) },
                method: { value: 'POST' },
                body: { value: { delivery: 'scenario' } },
                headers: { value: { 'Content-Type': 'application/json' } },
            },
        },
    }
}

const PARK_FOR = '1s'

type Flow = { name: string; trigger: object; actionId: string; step: object; parks: number }

function parkedFlow(teamId: number, { name, trigger, actionId, step, parks }: Flow): HogFlow {
    const parkIds = Array.from({ length: parks }, (_, i) => `park_${i + 1}`)
    const path = ['trigger', ...parkIds, actionId, 'exit']
    return new FixtureHogFlowBuilder()
        .withTeamId(teamId)
        .withName(name)
        .withStatus('active')
        .withExitCondition('exit_only_at_end')
        .withWorkflow({
            actions: {
                trigger: { type: 'trigger', config: trigger },
                ...Object.fromEntries(
                    parkIds.map((id) => [id, { type: 'delay', config: { delay_duration: PARK_FOR } }])
                ),
                [actionId]: step,
                exit: { type: 'exit', config: {} },
            },
            edges: path.slice(1).map((to, i) => ({ from: path[i], to, type: 'continue' })),
        } as Parameters<FixtureHogFlowBuilder['withWorkflow']>[0])
        .build()
}

export const kafkaEmit =
    (producer: Pick<KafkaProducerWrapper, 'produce'>, topic: string): Emit =>
    (unit, event, properties) =>
        produce(producer, topic, unit, event, properties)

async function produce(
    producer: Pick<KafkaProducerWrapper, 'produce'>,
    topic: string,
    unit: Unit,
    event: string,
    properties: object
): Promise<JournalEntry['answer']> {
    const incoming = createIncomingEvent(unit.teamId, {
        event,
        distinct_id: unit.unitId,
        properties: JSON.stringify(properties),
    })
    try {
        await producer.produce({
            topic,
            key: Buffer.from(incoming.distinct_id),
            value: Buffer.from(JSON.stringify(incoming)),
        })
        return { accepted: true }
    } catch (error) {
        return { accepted: false, transportError: String(error) }
    }
}

function localOnly<T>(part: T | undefined, name: string): T {
    if (part === undefined) {
        throw new Error(`this traffic kind needs the local ${name}, which only the local target offers`)
    }
    return part
}

function errorOf(body: string): string | undefined {
    try {
        const { error } = parseJSON(body) as { error?: unknown }
        return typeof error === 'string' ? error : undefined
    } catch {
        return undefined
    }
}

const EMAIL_EVENT = 'scenario_email'
const WEBHOOK_EVENT = 'scenario_webhook'

export const eventEmail: TrafficKind = {
    name: 'event_email',
    params: z.object({}).strict(),
    profile: Shape,
    intake: 'event',
    deliveries: [EMAIL_ACTION],
    unitLoad: (parks) => ({ claims: { hogflow: 1 + parks, email: 1 }, newJobs: 1 }),
    flow: async (teamId, emailIntegrationId, parks) =>
        parkedFlow(teamId, {
            name: 'Scenario event email',
            trigger: eventTrigger(EMAIL_EVENT),
            actionId: EMAIL_ACTION,
            step: await emailStep(emailIntegrationId, 'event.properties.email'),
            parks,
        }),
    offer: (unit, { emit }) => emit(unit, EMAIL_EVENT, { email: unitAddress(unit) }),
}

export const eventWebhook: TrafficKind = {
    name: 'event_webhook',
    params: z.object({}).strict(),
    profile: Shape,
    intake: 'event',
    deliveries: [WEBHOOK_ACTION],
    unitLoad: (parks) => ({ claims: { hogflow: 1 + parks, email: 0 }, newJobs: 1 }),
    flow: async (teamId, _emailIntegrationId, parks) =>
        parkedFlow(teamId, {
            name: 'Scenario event webhook',
            trigger: eventTrigger(WEBHOOK_EVENT),
            actionId: WEBHOOK_ACTION,
            step: await webhookStep(),
            parks,
        }),
    offer: (unit, { emit }) => emit(unit, WEBHOOK_EVENT, { unit_id: unit.unitId }),
}

export const transactionalEmail: TrafficKind = {
    name: 'transactional_email',
    params: z.object({}).strict(),
    profile: Shape,
    intake: 'transactional',
    deliveries: [EMAIL_ACTION],
    needsLocal: true,
    unitLoad: (parks) => ({ claims: { hogflow: 0, email: 1 + parks }, newJobs: 1 }),
    flow: async (teamId, emailIntegrationId, parks) =>
        parkedFlow(teamId, {
            name: 'Scenario transactional email',
            trigger: { type: 'api' },
            actionId: EMAIL_ACTION,
            step: await emailStep(emailIntegrationId, 'event.properties.to'),
            parks,
        }),
    offer: (unit, { cdpApi }, signal) => sendTransactional(unit, localOnly(cdpApi, 'CDP API'), signal),
}

const BOUNCE_EVENT = 'scenario_bounce'

export const bounceFollowup: TrafficKind = {
    name: 'bounce_followup',
    params: z.object({}).strict(),
    profile: Shape,
    intake: 'event',
    deliveries: [EMAIL_ACTION],
    needsLocal: true,
    flow: async (teamId, emailIntegrationId, parks) =>
        parkedFlow(teamId, {
            name: 'Scenario bounce email',
            trigger: eventTrigger(BOUNCE_EVENT),
            actionId: EMAIL_ACTION,
            step: await emailStep(emailIntegrationId, 'event.properties.email'),
            parks,
        }),
    offer: (unit, { emit }) => emit(unit, BOUNCE_EVENT, { email: unitAddress(unit) }),
    followUp: {
        flow: transactionalEmail.flow,
        offer: async (unit, { sesFeedback, cdpApi }, signal) => {
            const notSent = await localOnly(sesFeedback, 'SES feedback').settled(unit.unitId, signal)
            signal.throwIfAborted()
            return notSent === undefined ? sendTransactional(unit, localOnly(cdpApi, 'CDP API'), signal) : { notSent }
        },
    },
}

const SEND_RETRY = { backoffMs: 500, maxWaitMs: 5_000, deadlineMs: 60_000 }

export const REAL_CLOCK: SendClock = {
    now: () => performance.now(),
    wait: async (ms, signal) => {
        await sleep(ms, undefined, { signal })
    },
}

const withRetries = (answer: IntakeAnswer, retries: number): JournalEntry['answer'] =>
    retries === 0 ? answer : { ...answer, retries }

type CdpApi = NonNullable<OfferContext['cdpApi']>

const transactionalRequest = (unit: Unit): object => ({
    to: unitAddress(unit),
    distinct_id: unit.unitId,
    variables: {},
    idempotency_key: unit.unitId,
})

const sendTransactional = (unit: Unit, cdpApi: CdpApi, signal: AbortSignal): Promise<JournalEntry['answer']> =>
    retried(cdpApi, signal, () =>
        post(
            cdpApi,
            unit,
            flowRoute(unit, 'transactional_email'),
            { hog_flow_id: unit.flowId },
            transactionalRequest(unit)
        )
    )

async function retried(
    cdpApi: CdpApi,
    signal: AbortSignal,
    attempt: () => Promise<IntakeAnswer>
): Promise<JournalEntry['answer']> {
    const { backoffMs, maxWaitMs, deadlineMs } = SEND_RETRY
    const clock = cdpApi.clock ?? REAL_CLOCK
    const deadline = clock.now() + deadlineMs
    for (let retry = 0; ; retry += 1) {
        const answer = await attempt()
        const waitMs = Math.min(backoffMs * 2 ** retry, maxWaitMs)
        if (!('status' in answer) || answer.status < 500 || clock.now() + waitMs > deadline) {
            return withRetries(answer, retry)
        }
        await clock.wait(waitMs, signal)
        signal.throwIfAborted()
        if (clock.now() > deadline) {
            return withRetries(answer, retry)
        }
    }
}

const flowRoute = (unit: Unit, route: string): string =>
    `/api/projects/${unit.teamId}/hog_flows/${unit.flowId}/${route}`

type Posted = { answer: IntakeAnswer; body?: string }

async function post(cdpApi: CdpApi, unit: Unit, route: string, claims: object, request: object): Promise<IntakeAnswer> {
    return (await postReading(cdpApi, unit, route, claims, request)).answer
}

async function postReading(
    cdpApi: CdpApi,
    { teamId }: Unit,
    route: string,
    claims: object,
    request: object
): Promise<Posted> {
    try {
        const response = await internalFetch(`${cdpApi.nextUrl()}${route}`, {
            method: 'POST',
            headers: {
                'content-type': 'application/json',
                authorization: `Bearer ${cdpApi.jwt.mint({ team_id: teamId, ...claims })}`,
            },
            body: JSON.stringify(request),
        })
        const body = await response.text()
        return response.status >= 200 && response.status < 300
            ? { answer: { accepted: true }, body }
            : { answer: { accepted: false, status: response.status, outcome: errorOf(body) } }
    } catch (error) {
        return { answer: { accepted: false, transportError: String(error) } }
    }
}

const FILE_CONTENT_TYPE = 'application/pdf'
const BLOCK_BYTES = 64 * 1024
const PUT_TIMEOUT_MS = 60_000
// The send check counts the rendered bodies too, which outgrow the template by the links and pixel added at send.
const RENDERED_BODY_ALLOWANCE_BYTES = 16 * 1024

const fitsOneEmail = (sizes: readonly number[]): boolean =>
    estimateMessageBytes(sizes, [BODY.html, BODY.text], BODY.subject) + RENDERED_BODY_ALLOWANCE_BYTES <=
    MESSAGE_MAX_BYTES

function largestFittingFile(): number {
    let [fits, overflows] = [1, MESSAGE_MAX_BYTES]
    while (overflows - fits > 1) {
        const size = Math.floor((fits + overflows) / 2)
        if (fitsOneEmail([size])) {
            fits = size
        } else {
            overflows = size
        }
    }
    return fits
}

export const FILE_BYTES_AT_LIMIT = largestFittingFile()

export function fileBytes({ seed, sizeBytes }: UnitFile): Buffer {
    const block = Buffer.alloc(Math.min(BLOCK_BYTES, sizeBytes))
    let state = (seed ^ 0x9e3779b9) >>> 0 || 1
    for (let at = 0; at + 4 <= block.length; at += 4) {
        state ^= state << 13
        state ^= state >>> 17
        state ^= state << 5
        block.writeUInt32LE(state >>> 0, at)
    }
    return Buffer.alloc(sizeBytes, block)
}

const sha256Of = (bytes: Buffer): string => createHash('sha256').update(bytes).digest('hex')

const FileSize = z.union([z.number().int().positive(), z.literal('limit')])

const FilesShape = Shape.extend({
    parks: z.literal(0, { error: 'a send with files cannot park, its workflow is trigger, email, exit' }).default(0),
    files: z
        .object({
            share: z.number().min(0).max(1),
            perSend: z.number().int().min(1).max(MAX_EMAIL_ATTACHMENTS).default(1),
            sizes: z.array(z.object({ bytes: FileSize, weight: z.number().positive() }).strict()).min(1),
        })
        .strict(),
})
    .strict()
    .refine(
        ({ files }) => {
            const sizes = files.sizes.flatMap(({ bytes }) => (bytes === 'limit' ? [] : [bytes]))
            return sizes.length === 0 || fitsOneEmail(Array(files.perSend).fill(Math.max(...sizes)))
        },
        { message: `perSend files of the largest size must fit one email; use "limit" for a send at the limit` }
    )

const FilesParams = z
    .object({
        burst: z
            .object({ at: Duration, for: Duration, scale: z.number().gt(1) })
            .strict()
            .optional(),
    })
    .strict()

const UploadSlots = z.object({
    files: z.array(
        z.discriminatedUnion('status', [
            z.object({ sha256: z.string(), status: z.literal('present') }),
            z.object({
                sha256: z.string(),
                status: z.literal('upload'),
                url: z.string(),
                method: z.string(),
                headers: z.record(z.string(), z.string()),
            }),
        ])
    ),
})

type BuiltFile = { bytes: Buffer; sha256: string }

async function upload(unit: Unit, cdpApi: CdpApi, files: BuiltFile[]): Promise<IntakeAnswer> {
    const { answer, body } = await postReading(
        cdpApi,
        unit,
        `/api/projects/${unit.teamId}/transactional_email/attachments/uploads`,
        ATTACHMENT_UPLOAD_TOKEN_CLAIMS,
        { files: files.map(({ bytes, sha256 }) => ({ sha256, size: bytes.length })) }
    )
    if (!answer.accepted) {
        return 'status' in answer ? { ...answer, outcome: `uploads ${answer.outcome}` } : answer
    }
    const bytesOf = new Map(files.map(({ bytes, sha256 }) => [sha256, bytes]))
    const puts = UploadSlots.parse(parseJSON(body!)).files.map(async (slot): Promise<IntakeAnswer> => {
        if (slot.status === 'present') {
            return { accepted: true }
        }
        try {
            const { status } = await internalFetch(slot.url, {
                method: slot.method,
                headers: slot.headers,
                body: bytesOf.get(slot.sha256),
                timeoutMs: PUT_TIMEOUT_MS,
            })
            return status >= 200 && status < 300 ? { accepted: true } : { accepted: false, status, outcome: 'put' }
        } catch (error) {
            return { accepted: false, transportError: `put ${String(error)}` }
        }
    })
    return (await Promise.all(puts)).find((put) => !put.accepted) ?? { accepted: true }
}

async function sendWithFiles(unit: Unit, cdpApi: CdpApi, signal: AbortSignal): Promise<OfferAnswer> {
    const files = (unit.files ?? []).map((file) => {
        const bytes = fileBytes(file)
        return { bytes, sha256: sha256Of(bytes) }
    })
    const attachments = files.map(({ sha256 }, i) => ({
        sha256,
        filename: `scenario-${i + 1}.pdf`,
        content_type: FILE_CONTENT_TYPE,
    }))
    const request = {
        ...transactionalRequest(unit),
        send: { tracking: { captureEngagement: false }, ...(attachments.length > 0 && { attachments }) },
    }
    const answer = await retried(cdpApi, signal, async () => {
        const uploaded = files.length > 0 ? await upload(unit, cdpApi, files) : { accepted: true as const }
        return uploaded.accepted
            ? post(
                  cdpApi,
                  unit,
                  flowRoute(unit, 'transactional_email/send'),
                  { hog_flow_id: unit.flowId, ...CODE_SEND_TOKEN_CLAIMS },
                  request
              )
            : uploaded
    })
    return { ...answer, attachments: attachments.map(({ sha256 }) => sha256) }
}

export const transactionalEmailFiles: TrafficKind = {
    name: 'transactional_email_files',
    params: FilesParams,
    profile: FilesShape,
    intake: 'transactional',
    deliveries: [EMAIL_ACTION],
    needsLocal: true,
    unitLoad: () => ({ claims: { hogflow: 0, email: 1 }, newJobs: 1 }),
    flow: async (teamId, emailIntegrationId) =>
        parkedFlow(teamId, {
            name: 'Scenario transactional email with files',
            trigger: { type: 'api' },
            actionId: EMAIL_ACTION,
            step: await emailStep(emailIntegrationId, 'event.properties.to', {
                message_category_type: 'transactional',
            }),
            parks: 0,
        }),
    offer: (unit, { cdpApi }, signal) => sendWithFiles(unit, localOnly(cdpApi, 'CDP API'), signal),
    burstOf: (params) => {
        const { burst } = FilesParams.parse(params)
        return burst && { fromMs: durationMs(burst.at), forMs: durationMs(burst.for), scale: burst.scale }
    },
    filesOf: (chance, profile, atLimit) => {
        const { files } = FilesShape.parse(profile)
        const seed = (): number => chance.integer({ min: 0, max: 2 ** 32 - 1 })
        if (atLimit) {
            return [{ seed: seed(), sizeBytes: FILE_BYTES_AT_LIMIT }]
        }
        if (!chance.bool({ likelihood: files.share * 100 })) {
            return []
        }
        const drawn = Array.from({ length: files.perSend }, () =>
            chance.weighted(
                files.sizes.map(({ bytes }) => bytes),
                files.sizes.map(({ weight }) => weight)
            )
        )
        const sizes = drawn.includes('limit') ? [FILE_BYTES_AT_LIMIT] : (drawn as number[])
        return sizes.map((sizeBytes) => ({ seed: seed(), sizeBytes }))
    },
}

const CAPTURE_EVENT = 'scenario_offer'

export const captureWebhook: TrafficKind = {
    name: 'capture_webhook',
    params: z.object({}).strict(),
    profile: Shape,
    intake: 'capture',
    deliveries: [WEBHOOK_ACTION],
    flow: () => Promise.reject(new Error('capture_webhook drives a workflow a person made once on the target')),
    offer: (unit, { emit }) => emit(unit, CAPTURE_EVENT, { unit_id: unit.unitId }),
}

export const TRAFFIC: TrafficKind[] = [
    eventEmail,
    eventWebhook,
    transactionalEmail,
    transactionalEmailFiles,
    bounceFollowup,
    captureWebhook,
]
