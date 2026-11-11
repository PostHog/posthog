import { z } from 'zod'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { createIncomingEvent } from '~/cdp/_tests/fixtures'
import { CyclotronInputType } from '~/cdp/schema/cyclotron'
import { HogFlow } from '~/cdp/schema/hogflow'
import { compileHog } from '~/cdp/templates/compiler'
import type { KafkaProducerWrapper } from '~/common/kafka/producer'

import type { TrafficDefinition } from '../cards/definitions'
import type { JournalEntry } from '../judge/judge'
import { UNIT_EMAIL_DOMAIN } from '../provider-edge'

const Rate = z.object({ ratePerSecond: z.number().positive() }).strict()

export type Unit = { unitId: string; teamId: number }

export type OfferContext = { producer: Pick<KafkaProducerWrapper, 'produce'>; eventsTopic: string }

export type TrafficKind = Omit<TrafficDefinition, 'profile'> & {
    profile: typeof Rate
    intake: JournalEntry['kind']
    deliveries: string[]
    flow(teamId: number, emailIntegrationId: number): Promise<HogFlow>
    offer(unit: Unit, context: OfferContext): Promise<JournalEntry['answer']>
}

export const SENDER = { email: 'flows@www.example.com', name: 'Scenario runner', domain: 'www.example.com' }

const MATCH_EVERY_EVENT = { events: [], actions: [], bytecode: ['_H', 1, 29] }
const EMAIL_ACTION = 'email'

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

async function produce(context: OfferContext, unit: Unit, properties: object): Promise<JournalEntry['answer']> {
    const event = createIncomingEvent(unit.teamId, {
        event: 'scenario_unit',
        distinct_id: unit.unitId,
        properties: JSON.stringify(properties),
    })
    try {
        await context.producer.produce({
            topic: context.eventsTopic,
            key: Buffer.from(event.distinct_id),
            value: Buffer.from(JSON.stringify(event)),
        })
        return { accepted: true }
    } catch (error) {
        return { accepted: false, transportError: String(error) }
    }
}

export const eventEmail: TrafficKind = {
    name: 'event_email',
    params: z.object({}).strict(),
    profile: Rate,
    intake: 'event',
    deliveries: [EMAIL_ACTION],
    flow: async (teamId, emailIntegrationId) =>
        new FixtureHogFlowBuilder()
            .withTeamId(teamId)
            .withName('Scenario event email')
            .withStatus('active')
            .withExitCondition('exit_only_at_end')
            .withWorkflow({
                actions: {
                    trigger: { type: 'trigger', config: { type: 'event', filters: MATCH_EVERY_EVENT } },
                    [EMAIL_ACTION]: {
                        type: 'function_email',
                        config: {
                            template_id: 'template-email',
                            inputs: { email: await emailInput(emailIntegrationId, 'event.properties.email') },
                        },
                    },
                    exit: { type: 'exit', config: {} },
                },
                edges: [
                    { from: 'trigger', to: EMAIL_ACTION, type: 'continue' },
                    { from: EMAIL_ACTION, to: 'exit', type: 'continue' },
                ],
            })
            .build(),
    offer: (unit, context) => produce(context, unit, { email: `${unit.unitId}@${UNIT_EMAIL_DOMAIN}` }),
}

export const TRAFFIC: TrafficKind[] = [eventEmail]
