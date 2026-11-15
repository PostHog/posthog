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
import type { FollowUpAnswer, JournalEntry } from '../judge/judge'
import { UNIT_EMAIL_DOMAIN, WEBHOOK_HOST } from '../provider-edge'
import type { SesFeedback } from './ses-feedback'

const Rate = z.object({ ratePerSecond: z.number().positive() }).strict()

export type Unit = { unitId: string; teamId: number; flowId: string }

export type OfferContext = {
    producer: Pick<KafkaProducerWrapper, 'produce'>
    eventsTopic: string
    cdpApi: { url: string; jwt: Pick<ScopedServiceJwt, 'mint'> }
    sesFeedback: SesFeedback
}

export type TrafficKind = Omit<TrafficDefinition, 'profile'> & {
    profile: typeof Rate
    intake: JournalEntry['kind']
    deliveries: string[]
    flow(teamId: number, emailIntegrationId: number): Promise<HogFlow>
    offer(unit: Unit, context: OfferContext): Promise<JournalEntry['answer']>
    followUp?: {
        flow(teamId: number, emailIntegrationId: number): Promise<HogFlow>
        offer(unit: Unit, context: OfferContext, signal: AbortSignal): Promise<FollowUpAnswer>
    }
}

export const SENDER = { email: 'flows@www.example.com', name: 'Scenario runner', domain: 'www.example.com' }

const EMAIL_ACTION = 'email'
const WEBHOOK_ACTION = 'webhook'

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

function oneStepFlow(teamId: number, name: string, trigger: object, actionId: string, step: object): HogFlow {
    return new FixtureHogFlowBuilder()
        .withTeamId(teamId)
        .withName(name)
        .withStatus('active')
        .withExitCondition('exit_only_at_end')
        .withWorkflow({
            actions: {
                trigger: { type: 'trigger', config: trigger },
                [actionId]: step,
                exit: { type: 'exit', config: {} },
            },
            edges: [
                { from: 'trigger', to: actionId, type: 'continue' },
                { from: actionId, to: 'exit', type: 'continue' },
            ],
        } as Parameters<FixtureHogFlowBuilder['withWorkflow']>[0])
        .build()
}

async function produce(
    context: OfferContext,
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
        await context.producer.produce({
            topic: context.eventsTopic,
            key: Buffer.from(incoming.distinct_id),
            value: Buffer.from(JSON.stringify(incoming)),
        })
        return { accepted: true }
    } catch (error) {
        return { accepted: false, transportError: String(error) }
    }
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
    profile: Rate,
    intake: 'event',
    deliveries: [EMAIL_ACTION],
    flow: async (teamId, emailIntegrationId) =>
        oneStepFlow(
            teamId,
            'Scenario event email',
            eventTrigger(EMAIL_EVENT),
            EMAIL_ACTION,
            await emailStep(emailIntegrationId, 'event.properties.email')
        ),
    offer: (unit, context) => produce(context, unit, EMAIL_EVENT, { email: unitAddress(unit) }),
}

export const eventWebhook: TrafficKind = {
    name: 'event_webhook',
    params: z.object({}).strict(),
    profile: Rate,
    intake: 'event',
    deliveries: [WEBHOOK_ACTION],
    flow: async (teamId) =>
        oneStepFlow(teamId, 'Scenario event webhook', eventTrigger(WEBHOOK_EVENT), WEBHOOK_ACTION, await webhookStep()),
    offer: (unit, context) => produce(context, unit, WEBHOOK_EVENT, { unit_id: unit.unitId }),
}

export const transactionalEmail: TrafficKind = {
    name: 'transactional_email',
    params: z.object({}).strict(),
    profile: Rate,
    intake: 'transactional',
    deliveries: [EMAIL_ACTION],
    flow: async (teamId, emailIntegrationId) =>
        oneStepFlow(
            teamId,
            'Scenario transactional email',
            { type: 'api' },
            EMAIL_ACTION,
            await emailStep(emailIntegrationId, 'event.properties.to')
        ),
    offer: (unit, { cdpApi }) => sendTransactional(unit, cdpApi),
}

const BOUNCE_EVENT = 'scenario_bounce'

export const bounceFollowup: TrafficKind = {
    name: 'bounce_followup',
    params: z.object({}).strict(),
    profile: Rate,
    intake: 'event',
    deliveries: [EMAIL_ACTION],
    flow: async (teamId, emailIntegrationId) =>
        oneStepFlow(
            teamId,
            'Scenario bounce email',
            eventTrigger(BOUNCE_EVENT),
            EMAIL_ACTION,
            await emailStep(emailIntegrationId, 'event.properties.email')
        ),
    offer: (unit, context) => produce(context, unit, BOUNCE_EVENT, { email: unitAddress(unit) }),
    followUp: {
        flow: transactionalEmail.flow,
        offer: async (unit, { sesFeedback, cdpApi }, signal) => {
            const notSent = await sesFeedback.settled(unit.unitId, signal)
            signal.throwIfAborted()
            return notSent === undefined ? sendTransactional(unit, cdpApi) : { notSent }
        },
    },
}

async function sendTransactional(unit: Unit, cdpApi: OfferContext['cdpApi']): Promise<JournalEntry['answer']> {
    try {
        const response = await internalFetch(
            `${cdpApi.url}/api/projects/${unit.teamId}/hog_flows/${unit.flowId}/transactional_email`,
            {
                method: 'POST',
                headers: {
                    'content-type': 'application/json',
                    authorization: `Bearer ${cdpApi.jwt.mint({ team_id: unit.teamId, hog_flow_id: unit.flowId })}`,
                },
                body: JSON.stringify({ to: unitAddress(unit), distinct_id: unit.unitId, variables: {} }),
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

export const TRAFFIC: TrafficKind[] = [eventEmail, eventWebhook, transactionalEmail, bounceFollowup]
