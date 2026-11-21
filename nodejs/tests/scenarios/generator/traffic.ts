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
import type { FollowUpAnswer, IntakeAnswer, JournalEntry } from '../judge/judge'
import { UNIT_EMAIL_DOMAIN, WEBHOOK_HOST } from '../provider-edge'
import type { SesFeedback } from './ses-feedback'

const Shape = z.object({ ratePerSecond: z.number().positive(), parks: z.number().int().min(0).default(0) }).strict()

export type Unit = { unitId: string; teamId: number; flowId: string }

export type Emit = (unit: Unit, event: string, properties: object) => Promise<IntakeAnswer>

export type SendClock = { now(): number; wait(ms: number, signal: AbortSignal): Promise<void> }

export type OfferContext = {
    emit: Emit
    cdpApi?: { url: string; jwt: Pick<ScopedServiceJwt, 'mint'>; clock?: SendClock }
    sesFeedback?: SesFeedback
}

export type TrafficKind = Omit<TrafficDefinition, 'profile'> & {
    profile: typeof Shape
    intake: JournalEntry['kind']
    deliveries: string[]
    needsLocal?: true
    flow(teamId: number, emailIntegrationId: number, parks: number): Promise<HogFlow>
    offer(unit: Unit, context: OfferContext, signal: AbortSignal): Promise<JournalEntry['answer']>
    followUp?: {
        flow(teamId: number, emailIntegrationId: number, parks: number): Promise<HogFlow>
        offer(unit: Unit, context: OfferContext, signal: AbortSignal): Promise<FollowUpAnswer>
    }
}

export const SENDER = { email: 'flows@www.example.com', name: 'Scenario runner', domain: 'www.example.com' }

const EMAIL_ACTION = 'email'
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

async function sendTransactional(
    unit: Unit,
    cdpApi: NonNullable<OfferContext['cdpApi']>,
    signal: AbortSignal
): Promise<JournalEntry['answer']> {
    const { backoffMs, maxWaitMs, deadlineMs } = SEND_RETRY
    const clock = cdpApi.clock ?? REAL_CLOCK
    const request = { to: unitAddress(unit), distinct_id: unit.unitId, variables: {}, idempotency_key: unit.unitId }
    const deadline = clock.now() + deadlineMs
    for (let retry = 0; ; retry += 1) {
        const answer = await postTransactional(unit, cdpApi, request)
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

async function postTransactional(
    unit: Unit,
    cdpApi: NonNullable<OfferContext['cdpApi']>,
    request: object
): Promise<IntakeAnswer> {
    try {
        const response = await internalFetch(
            `${cdpApi.url}/api/projects/${unit.teamId}/hog_flows/${unit.flowId}/transactional_email`,
            {
                method: 'POST',
                headers: {
                    'content-type': 'application/json',
                    authorization: `Bearer ${cdpApi.jwt.mint({ team_id: unit.teamId, hog_flow_id: unit.flowId })}`,
                },
                body: JSON.stringify(request),
            }
        )
        const body = await response.text()
        return response.status >= 200 && response.status < 300
            ? { accepted: true }
            : { accepted: false, status: response.status, outcome: errorOf(body) }
    } catch (error) {
        return { accepted: false, transportError: String(error) }
    }
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

export const TRAFFIC: TrafficKind[] = [eventEmail, eventWebhook, transactionalEmail, bounceFollowup, captureWebhook]
