import { setTimeout as sleep } from 'timers/promises'
import { z } from 'zod'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { createIncomingEvent } from '~/cdp/_tests/fixtures'
import { CyclotronInputType } from '~/cdp/schema/cyclotron'
import { HogFlow } from '~/cdp/schema/hogflow'
import { compileHog } from '~/cdp/templates/compiler'
import type { ScopedServiceJwt } from '~/cdp/utils/scoped-service-jwt'
import type { KafkaProducerWrapper } from '~/common/kafka/producer'
import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'

import type { TrafficDefinition } from '../cards/definitions'
import { mayHaveQueued } from '../judge/invariants'
import type { FollowUpAnswer, IntakeAnswer, JournalEntry } from '../judge/judge'
import { UNIT_EMAIL_DOMAIN, WEBHOOK_HOST } from '../provider-edge'
import type { SesFeedback } from './ses-feedback'

const Shape = z.object({ ratePerSecond: z.number().positive(), parks: z.number().int().min(0).default(0) }).strict()

export type Unit = { unitId: string; teamId: number; flowId: string }

export type Emit = (unit: Unit, event: string, properties: object) => Promise<IntakeAnswer>

export type SendClock = { now(): number; wait(ms: number, signal: AbortSignal): Promise<void> }

export type OfferContext = {
    emit: Emit
    cdpApi?: { nextUrl: () => string; jwt: Pick<ScopedServiceJwt, 'mint'>; clock?: SendClock }
    sesFeedback?: SesFeedback
}

export type UnitLoad = { claims: { hogflow: number; email: number }; newJobs: number }

export type TrafficKind = Omit<TrafficDefinition, 'profile'> & {
    profile: typeof Shape
    intake: JournalEntry['kind']
    deliveries: string[]
    needsLocal?: true
    unitLoad?(parks: number): UnitLoad
    flow(teamId: number, emailIntegrationId: number, parks: number): Promise<HogFlow>
    offer(unit: Unit, context: OfferContext, signal: AbortSignal): Promise<JournalEntry['answer']>
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

async function emailInput(emailIntegrationId: number, recipient: string): Promise<CyclotronInputType> {
    const message = (to: unknown): Record<string, unknown> => ({
        to: { email: to, name: '' },
        from: { integrationId: emailIntegrationId, email: SENDER.email },
        subject: 'Scenario delivery',
        text: 'Scenario delivery',
        html: '<p>Scenario delivery</p>',
    })
    return {
        templating: 'hog',
        value: message(`{${recipient}}`),
        bytecode: message(await compileHog(`return ${recipient}`)),
    }
}

const emailStep = async (emailIntegrationId: number, recipient: string): Promise<object> => ({
    type: 'function_email',
    config: { template_id: 'template-email', inputs: { email: await emailInput(emailIntegrationId, recipient) } },
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
        const { error, status } = parseJSON(body) as { error?: unknown; status?: unknown }
        return typeof error === 'string' ? error : typeof status === 'string' ? status : undefined
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

export const INTAKE_ANSWER_TIMEOUT_MS = 10_000

export const REAL_CLOCK: SendClock = {
    now: () => performance.now(),
    wait: async (ms, signal) => {
        await sleep(ms, undefined, { signal })
    },
}

const withRetries = (answer: IntakeAnswer, retries: number, unconfirmedAttempt: boolean): JournalEntry['answer'] => ({
    ...answer,
    ...(retries === 0 ? {} : { retries }),
    ...(unconfirmedAttempt && !answer.accepted ? { unconfirmedAttempt: true as const } : {}),
})

function sendTransactional(
    unit: Unit,
    cdpApi: NonNullable<OfferContext['cdpApi']>,
    signal: AbortSignal
): Promise<JournalEntry['answer']> {
    const request = { to: unitAddress(unit), distinct_id: unit.unitId, variables: {}, idempotency_key: unit.unitId }
    return sendWithRetries(() => postTransactional(unit, cdpApi, request), cdpApi.clock ?? REAL_CLOCK, signal)
}

async function sendWithRetries(
    post: () => Promise<IntakeAnswer>,
    clock: SendClock,
    signal: AbortSignal
): Promise<JournalEntry['answer']> {
    const { backoffMs, maxWaitMs, deadlineMs } = SEND_RETRY
    const deadline = clock.now() + deadlineMs
    let unconfirmedAttempt = false
    for (let retry = 0; ; retry += 1) {
        const answer = await post()
        const waitMs = Math.min(backoffMs * 2 ** retry, maxWaitMs)
        if (!('status' in answer) || answer.status < 500 || clock.now() + waitMs > deadline) {
            return withRetries(answer, retry, unconfirmedAttempt)
        }
        await clock.wait(waitMs, signal)
        signal.throwIfAborted()
        if (clock.now() > deadline) {
            return withRetries(answer, retry, unconfirmedAttempt)
        }
        unconfirmedAttempt ||= mayHaveQueued(answer)
    }
}

function postTransactional(
    unit: Unit,
    cdpApi: NonNullable<OfferContext['cdpApi']>,
    request: object
): Promise<IntakeAnswer> {
    return postToIntake(() => ({
        url: `${cdpApi.nextUrl()}/api/projects/${unit.teamId}/hog_flows/${unit.flowId}/transactional_email`,
        headers: { authorization: `Bearer ${cdpApi.jwt.mint({ team_id: unit.teamId, hog_flow_id: unit.flowId })}` },
        body: request,
    }))
}

type IntakeRequest = { url: string; headers: Record<string, string>; body: object }

async function postToIntake(requestOf: () => IntakeRequest): Promise<IntakeAnswer> {
    try {
        const { url, headers, body } = requestOf()
        const response = await internalFetch(url, {
            timeoutMs: INTAKE_ANSWER_TIMEOUT_MS,
            method: 'POST',
            headers: { 'content-type': 'application/json', ...headers },
            body: JSON.stringify(body),
        })
        const text = await response.text()
        return response.status >= 200 && response.status < 300
            ? { accepted: true }
            : { accepted: false, status: response.status, outcome: errorOf(text) }
    } catch (error) {
        return { accepted: false, transportError: String(error) }
    }
}

const WEBHOOK_TRIGGER_EVENT = 'scenario_webhook_trigger'

const fromRequest = async (template: string): Promise<CyclotronInputType> => ({
    value: template,
    bytecode: await compileHog(`return f'${template}'`),
})

const webhookTrigger = async (): Promise<object> => ({
    type: 'webhook',
    template_id: 'template-source-webhook',
    inputs: {
        event: await fromRequest(WEBHOOK_TRIGGER_EVENT),
        distinct_id: await fromRequest('{request.body.unit_id}'),
        properties: {
            value: { unit_id: '{request.body.unit_id}' },
            bytecode: { unit_id: await compileHog(`return f'{request.body.unit_id}'`) },
        },
        method: await fromRequest('POST'),
    },
})

function postWebhookTrigger(unit: Unit, cdpApi: NonNullable<OfferContext['cdpApi']>): Promise<IntakeAnswer> {
    return postToIntake(() => ({
        url: `${cdpApi.nextUrl()}/public/webhooks/${unit.flowId}`,
        headers: { 'idempotency-key': unit.unitId },
        body: { unit_id: unit.unitId },
    }))
}

export const workflowWebhook: TrafficKind = {
    name: 'workflow_webhook',
    params: z.object({}).strict(),
    profile: Shape,
    intake: 'webhook',
    deliveries: [WEBHOOK_ACTION],
    needsLocal: true,
    unitLoad: (parks) => ({ claims: { hogflow: 1 + parks, email: 0 }, newJobs: 1 }),
    flow: async (teamId, _emailIntegrationId, parks) =>
        parkedFlow(teamId, {
            name: 'Scenario workflow webhook',
            trigger: await webhookTrigger(),
            actionId: WEBHOOK_ACTION,
            step: await webhookStep(),
            parks,
        }),
    offer: (unit, { cdpApi }, signal) => {
        const api = localOnly(cdpApi, 'CDP API')
        return sendWithRetries(() => postWebhookTrigger(unit, api), api.clock ?? REAL_CLOCK, signal)
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
    bounceFollowup,
    captureWebhook,
    workflowWebhook,
]
