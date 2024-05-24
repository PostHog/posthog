import { Action, ISOTimestamp, PostIngestionEvent, Team } from '../../../src/types'
import { WebhookFormatter } from '../../../src/worker/ingestion/webhook-formatter'

type WebhookFormatterOptions = {
    webhookUrl?: string
    messageFormat?: string
    action?: Action
    event?: PostIngestionEvent
    team?: Team
    siteUrl?: string
    personProperties?: PostIngestionEvent['person_properties']
}

describe('WebhookFormatter', () => {
    const team = { id: 123, person_display_name_properties: null } as Team
    const action = {
        id: 1,
        name: 'action1',
    } as Action
    const event: PostIngestionEvent = {
        event: '$pageview',
        eventUuid: '123',
        teamId: 123,
        distinctId: 'WALL-E',
        person_properties: { email: 'test@posthog.com' },
        person_created_at: '2021-10-31T00%3A44%3A00.000Z' as ISOTimestamp,

        elementsList: [],
        properties: { $browser: 'Chrome' },
        timestamp: '2021-10-31T00%3A44%3A00.000Z' as ISOTimestamp,
    }

    const createFormatter = (options?: WebhookFormatterOptions) => {
        return new WebhookFormatter(
            options?.webhookUrl ?? 'https://example.com/',
            options?.messageFormat ?? 'User [person] did [action.name]',
            options?.action ?? action,
            {
                ...(options?.event ?? event),
                person_properties: options?.personProperties ?? event.person_properties,
            },
            options?.team ?? team,
            options?.siteUrl ?? 'http://localhost:8000'
        )
    }

    beforeEach(() => {
        process.env.NODE_ENV = 'test'
    })

    describe('webhook formatting options', () => {
        const cases: [WebhookFormatterOptions][] = [
            [{ messageFormat: '[person]' }],
            [{ messageFormat: '[person.link]' }],
            [{ messageFormat: '[user.name]' }], // Alias for person name
            [{ messageFormat: '[user.browser]' }], // Otherwise just alias to event properties
            [{ messageFormat: '[action.name]' }],
            [{ messageFormat: '[action.name] was done by [user.name]' }],
            // Handle escaping brackets
            [{ messageFormat: '[action.name\\] got done by \\[user.name\\]' }],
            [{ messageFormat: '[event]' }],
            [{ messageFormat: '[event.uuid]' }],
            [{ messageFormat: '[event.name]' }], // Alias for event name
            [{ messageFormat: '[event.event]' }],
            [{ messageFormat: '[event.distinct_id]' }],
            [
                {
                    messageFormat: '[person]',
                    personProperties: {
                        imię: 'Grzegorz',
                        nazwisko: 'Brzęczyszczykiewicz',
                    },
                    team: { ...team, person_display_name_properties: ['nazwisko'] },
                },
            ],
            [
                {
                    messageFormat: '[person.properties.enjoys_broccoli_on_pizza]',
                    personProperties: { enjoys_broccoli_on_pizza: false },
                },
            ],
            [
                {
                    messageFormat: '[person.properties.pizza_ingredient_ranking]',
                    personProperties: { pizza_ingredient_ranking: ['pineapple', 'broccoli', 'aubergine'] },
                },
            ],
            [
                {
                    messageFormat: '[user.missing_property]',
                },
            ],
            [{ messageFormat: '[event]', event: { ...event, eventUuid: '**)', event: 'text](yes!), [new link' } }], // Special escaping
            [
                {
                    messageFormat:
                        '[user.name] from [user.browser] on [event.properties.page_title] page with [event.properties.fruit], [event.properties.with space]',
                    event: {
                        ...event,
                        distinctId: '2',
                        properties: { $browser: 'Chrome', page_title: 'Pricing', 'with space': 'yes sir' },
                    },
                },
            ],
        ]

        it.each(cases)('%s', (options) => {
            const formatter = createFormatter(options)
            const message = formatter.generateWebhookPayload()
            // For non-slack messages the text is always markdown
            expect(message.text).toMatchSnapshot()
        })
    })

    describe('slack webhook formatting options', () => {
        // Additional checks for the standard slack webhook formats
        const cases: [WebhookFormatterOptions][] = [
            [{ messageFormat: '[person]' }],
            [{ messageFormat: '[action.name]' }],
            [{ messageFormat: '[event]', event: { ...event, eventUuid: '**>)', event: 'text><new link' } }], // Special escaping
        ]

        it.each(cases)('%s', (options) => {
            const formatter = createFormatter({
                webhookUrl: 'https://hooks.slack.com/services/123/456/789',
                ...options,
            })
            const message = formatter.generateWebhookPayload()
            expect(message.text).toMatchSnapshot()
            expect(message.blocks[0].text.text).toMatchSnapshot()
        })
    })
})
