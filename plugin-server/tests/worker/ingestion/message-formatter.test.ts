import { ISOTimestamp, PostIngestionEvent, Team } from '../../../src/types'
import { MessageFormatter, MessageFormatterOptions } from '../../../src/worker/ingestion/message-formatter'

type TestWebhookFormatterOptions = Partial<MessageFormatterOptions> & {
    personProperties?: PostIngestionEvent['person_properties']
}

describe('MessageFormatter', () => {
    const team = { id: 123, person_display_name_properties: null } as Team
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
        groups: {
            organization: {
                index: 1,
                type: 'organization',
                key: '123',
                properties: { name: 'PostHog', plan: 'paid' },
            },

            project: {
                index: 2,
                type: 'project',
                key: '234',
                properties: {},
            },
        },
    }

    const createFormatter = (options?: TestWebhookFormatterOptions) => {
        return new MessageFormatter({
            sourceName: options?.sourceName ?? 'action1',
            sourcePath: options?.sourcePath ?? '/action/1',
            event: {
                ...(options?.event ?? event),
                person_properties: options?.personProperties ?? event.person_properties,
            },
            team: options?.team ?? team,
            siteUrl: options?.siteUrl ?? 'http://localhost:8000',
        })
    }

    beforeEach(() => {
        process.env.NODE_ENV = 'test'
    })

    describe('webhook formatting options', () => {
        const cases: [string, TestWebhookFormatterOptions][] = [
            ['{{person}}', {}],
            ['{{person.link}}', {}],
            ['{{user.name}}', {}], // Alias for person name
            ['{{user.browser}}', {}], // Otherwise just alias to event properties
            ['{{action.name}}', {}],
            ['{{action.name}} was done by {{user.name}}', {}],
            ['{{source.name}}', {}],
            ['{{source.name}} was done by {{user.name}}', {}],
            // Handle escaping brackets
            ['{{action.name\\}} got done by \\{{user.name\\}}', {}],
            ['{{event}}', {}],
            ['{{event.uuid}}', {}],
            ['{{event.name}}', {}], // Alias for event name
            ['{{event.event}}', {}],
            ['{{event.distinct_id}}', {}],
            [
                '{{person}}',
                {
                    personProperties: {
                        imię: 'Grzegorz',
                        nazwisko: 'Brzęczyszczykiewicz',
                    },
                    team: { ...team, person_display_name_properties: ['nazwisko'] },
                },
            ],
            [
                '{{person.properties.enjoys_broccoli_on_pizza}}',
                {
                    personProperties: { enjoys_broccoli_on_pizza: false },
                },
            ],
            [
                '{{person.properties.pizza_ingredient_ranking}}',
                {
                    personProperties: { pizza_ingredient_ranking: ['pineapple', 'broccoli', 'aubergine'] },
                },
            ],
            ['{{user.missing_property}}', {}],
            ['{{event}}', { event: { ...event, eventUuid: '**)', event: 'text](yes!), [new link' } }], // Special escaping
            [
                '{{user.name}} from {{user.browser}} on {{event.properties.page_title}} page with {{event.properties.fruit}}, {{event.properties.with space}}',
                {
                    event: {
                        ...event,
                        distinctId: '2',
                        properties: { $browser: 'Chrome', page_title: 'Pricing', 'with space': 'yes sir' },
                    },
                },
            ],
            ['{{groups}}', {}],
            ['{{groups.missing}}', {}],
            ['{{groups.organization}}', {}],
            ['{{groups.organization.properties.plan}}', {}],
            ['{{groups.project}}', {}], // No-name one
            ['{{ person.name}} did {{ event . event }}', {}], // Weird spacing
        ]

        it.each(cases)('format string %s %s', (template, options) => {
            const formatter = createFormatter(options)
            const message = formatter.format(template, 'string')
            console.log('Template:', template)
            console.log('Output:', message)
            // For non-slack messages the text is always markdown
            expect(message).toMatchSnapshot()
        })

        const jsonCases: [any, TestWebhookFormatterOptions][] = [
            // Strings where the whole template is an object should be formatted as JSON
            ['{{person}}', {}],
            ['{{event.properties}}', {}],
            // Special escaping
            ['{{event}}', { event: { ...event, eventUuid: '**)', event: 'text](yes!), [new link' } }], // Special escaping
            [
                '{{user.name}} from {{user.browser}} on {{event.properties.page_title}} page with {{event.properties.fruit}}, {{event.properties.with space}}',
                {
                    event: {
                        ...event,
                        distinctId: '2',
                        properties: { $browser: 'Chrome', page_title: 'Pricing', 'with space': 'yes sir' },
                    },
                },
            ],
            // Object with a range of values
            [
                {
                    event_properties: '{{event.properties}}',
                    person_link: '{{person.link}}',
                    missing: '{{event.properties.missing}}',
                },
                {},
            ],
        ]

        it.each(jsonCases)('format json %s %s', (jsonTemplate, options) => {
            const formatter = createFormatter(options)
            const message = formatter.format(JSON.stringify(jsonTemplate), 'json')
            console.log('Template:', jsonTemplate)
            console.log('Output:', message)
            // For non-slack messages the text is always markdown
            expect(message).toMatchSnapshot()
            expect(() => JSON.parse(message)).not.toThrow()
        })

        it('should handle an advanced case', () => {
            const formatter = createFormatter({
                event: {
                    properties: {
                        array_item: ['item1', 'item2'],
                        bad_string: '\n`"\'\\',
                    },
                    groups: {
                        organization: {
                            properties: { name: 'PostHog', plan: 'paid' },
                        },
                    },
                },
            })
            const message = formatter.format(
                JSON.stringify(
                    {
                        event_properties: 'json: {{event.properties}}',
                        string_with_complex_properties:
                            'This is a string with {{event.properties.array_item}} and {{event.properties.bad_string}}',
                        bad_string: '{{event.properties.bad_string}}',
                        object_in_string: '{{groups.organization.properties}}',
                    },
                    null,
                    2
                )
            )
            console.log('Message:', message)
            expect(() => JSON.parse(message)).not.toThrow()
            expect(message).toMatchSnapshot()
            const parsed = JSON.parse(message)

            expect(parsed).toMatchInlineSnapshot(`
                Object {
                  "bad_string": "
                \`\\"'\\\\",
                  "event_properties": "json: {\\"array_item\\":[\\"item1\\",\\"item2\\"],\\"bad_string\\":\\"\\\\n\`\\\\\\"'\\\\\\\\\\"}",
                  "object_in_string": Object {
                    "name": "PostHog",
                    "plan": "paid",
                  },
                  "string_with_complex_properties": "This is a string with [\\"item1\\",\\"item2\\"] and 
                \`\\"'\\\\",
                }
            `)
        })
    })
})
