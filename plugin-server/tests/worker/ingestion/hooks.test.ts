import { DateTime } from 'luxon'
import fetch, { FetchError } from 'node-fetch'

import { Action, PostIngestionEvent, Team } from '../../../src/types'
import { UUIDT } from '../../../src/utils/utils'
import { AppMetrics } from '../../../src/worker/ingestion/app-metrics'
import {
    determineWebhookType,
    getActionDetails,
    getFormattedMessage,
    getPersonDetails,
    getTokens,
    getValueOfToken,
    HookCommander,
    WebhookType,
} from '../../../src/worker/ingestion/hooks'
import { Hook } from './../../../src/types'

describe('hooks', () => {
    beforeEach(() => {
        process.env.NODE_ENV = 'test'
    })

    describe('determineWebhookType', () => {
        test('Slack', () => {
            const webhookType = determineWebhookType('https://hooks.slack.com/services/')

            expect(webhookType).toBe(WebhookType.Slack)
        })

        test('Discord', () => {
            const webhookType = determineWebhookType('https://discord.com/api/webhooks/')

            expect(webhookType).toBe(WebhookType.Discord)
        })

        test('Teams', () => {
            const webhookType = determineWebhookType('https://outlook.office.com/webhook/')

            expect(webhookType).toBe(WebhookType.Teams)
        })
    })

    describe('getPersonDetails', () => {
        const event = {
            distinctId: 'WALL-E',
            person_properties: { email: 'test@posthog.com' },
        } as unknown as PostIngestionEvent
        const team = { person_display_name_properties: null } as Team

        test('Slack', () => {
            const [userDetails, userDetailsMarkdown] = getPersonDetails(
                event,
                'http://localhost:8000',
                WebhookType.Slack,
                team
            )

            expect(userDetails).toBe('test@posthog.com')
            expect(userDetailsMarkdown).toBe('<http://localhost:8000/person/WALL-E|test@posthog.com>')
        })

        test('Teams', () => {
            const [userDetails, userDetailsMarkdown] = getPersonDetails(
                event,
                'http://localhost:8000',
                WebhookType.Teams,
                team
            )

            expect(userDetails).toBe('test@posthog.com')
            expect(userDetailsMarkdown).toBe('[test@posthog.com](http://localhost:8000/person/WALL-E)')
        })
    })

    describe('getActionDetails', () => {
        const action = { id: 1, name: 'action1' } as Action

        test('Slack', () => {
            const [actionDetails, actionDetailsMarkdown] = getActionDetails(
                action,
                'http://localhost:8000',
                WebhookType.Slack
            )

            expect(actionDetails).toBe('action1')
            expect(actionDetailsMarkdown).toBe('<http://localhost:8000/action/1|action1>')
        })

        test('Teams', () => {
            const [actionDetails, actionDetailsMarkdown] = getActionDetails(
                action,
                'http://localhost:8000',
                WebhookType.Teams
            )

            expect(actionDetails).toBe('action1')
            expect(actionDetailsMarkdown).toBe('[action1](http://localhost:8000/action/1)')
        })
    })

    describe('getTokens', () => {
        test('works', () => {
            const format = '[action.name] got done by [user.name]'

            const [matchedTokens, tokenisedMessage] = getTokens(format)

            expect(matchedTokens).toStrictEqual(['action.name', 'user.name'])
            expect(tokenisedMessage).toBe('%s got done by %s')
        })

        test('allows escaping brackets', () => {
            const format = '[action.name\\] got done by \\[user.name\\]' // just one of the brackets has to be escaped

            const [matchedTokens, tokenisedMessage] = getTokens(format)

            expect(matchedTokens).toStrictEqual([])
            expect(tokenisedMessage).toBe('[action.name] got done by [user.name]')
        })
    })

    describe('getValueOfToken', () => {
        const action = { id: 1, name: 'action1' } as Action
        const event = {
            eventUuid: '123',
            event: '$pageview',
            distinctId: 'WALL-E',
            properties: { $browser: 'Chrome' },
            person_properties: { enjoys_broccoli_on_pizza: false },
            timestamp: '2021-10-31T00:44:00.000Z',
        } as unknown as PostIngestionEvent
        const team = { person_display_name_properties: null } as Team

        test('event', () => {
            const tokenUserName = ['event']

            const [text, markdown] = getValueOfToken(
                action,
                event,
                team,
                'http://localhost:8000',
                WebhookType.Teams,
                tokenUserName
            )

            expect(text).toBe('$pageview')
            expect(markdown).toBe('[$pageview](http://localhost:8000/events/123/2021-10-31T00%3A44%3A00.000Z)')
        })

        test('event UUID', () => {
            const tokenUserName = ['event', 'uuid']

            const [text, markdown] = getValueOfToken(
                action,
                event,
                team,
                'http://localhost:8000',
                WebhookType.Teams,
                tokenUserName
            )

            expect(text).toBe('123')
            expect(markdown).toBe('123')
        })

        test('event name', () => {
            const tokenUserName = ['event', 'name']

            const [text, markdown] = getValueOfToken(
                action,
                event,
                team,
                'http://localhost:8000',
                WebhookType.Teams,
                tokenUserName
            )

            expect(text).toBe('$pageview')
            expect(markdown).toBe('$pageview')
        })

        test('event event', () => {
            const tokenUserName = ['event', 'event']

            const [text, markdown] = getValueOfToken(
                action,
                event,
                team,
                'http://localhost:8000',
                WebhookType.Teams,
                tokenUserName
            )

            expect(text).toBe('$pageview')
            expect(markdown).toBe('$pageview')
        })

        test('event distinct_id', () => {
            const tokenUserName = ['event', 'distinct_id']

            const [text, markdown] = getValueOfToken(
                action,
                event,
                team,
                'http://localhost:8000',
                WebhookType.Teams,
                tokenUserName
            )

            expect(text).toBe('WALL-E')
            expect(markdown).toBe('WALL-E')
        })

        test('person with just distinct ID', () => {
            const tokenUserName = ['person']

            const [text, markdown] = getValueOfToken(
                action,
                event,
                team,
                'http://localhost:8000',
                WebhookType.Teams,
                tokenUserName
            )

            expect(text).toBe('WALL-E')
            expect(markdown).toBe('[WALL-E](http://localhost:8000/person/WALL-E)')
        })

        test('person with email', () => {
            const tokenUserName = ['person']

            const [text, markdown] = getValueOfToken(
                action,
                { ...event, person_properties: { ...event.person_properties, email: 'wall-e@buynlarge.com' } },
                team,
                'http://localhost:8000',
                WebhookType.Teams,
                tokenUserName
            )

            expect(text).toBe('wall-e@buynlarge.com')
            expect(markdown).toBe('[wall-e@buynlarge.com](http://localhost:8000/person/WALL-E)')
        })

        test('person with custom name property, team-level setting ', () => {
            const tokenUserName = ['person']

            const [text, markdown] = getValueOfToken(
                action,
                {
                    ...event,
                    person_properties: {
                        ...event.person_properties,
                        imię: 'Grzegorz',
                        nazwisko: 'Brzęczyszczykiewicz',
                    },
                    distinctId: 'fd',
                },
                { ...team, person_display_name_properties: ['nazwisko'] },
                'http://localhost:8000',
                WebhookType.Teams,
                tokenUserName
            )

            expect(text).toBe('Brzęczyszczykiewicz')
            expect(markdown).toBe('[Brzęczyszczykiewicz](http://localhost:8000/person/fd)')
        })

        test('person prop', () => {
            const tokenUserPropString = ['person', 'properties', 'enjoys_broccoli_on_pizza']

            const [text, markdown] = getValueOfToken(
                action,
                event,
                team,
                'http://localhost:8000',
                WebhookType.Teams,
                tokenUserPropString
            )

            expect(text).toBe('false')
            expect(markdown).toBe('false')
        })

        test('person prop nested', () => {
            const tokenUserPropString = ['person', 'properties', 'pizza_ingredient_scores', 'broccoli']

            const [text, markdown] = getValueOfToken(
                action,
                {
                    ...event,
                    person_properties: {
                        ...event.person_properties,
                        pizza_ingredient_scores: { broccoli: 5, pineapple: 9, aubergine: 0 },
                    },
                },
                team,
                'http://localhost:8000',
                WebhookType.Teams,
                tokenUserPropString
            )

            expect(text).toBe('5')
            expect(markdown).toBe('5')
        })

        test('person prop non-primitive', () => {
            const tokenUserPropString = ['person', 'properties', 'pizza_ingredient_ranking']

            const [text, markdown] = getValueOfToken(
                action,
                {
                    ...event,
                    person_properties: {
                        ...event.person_properties,
                        pizza_ingredient_ranking: ['pineapple', 'broccoli', 'aubergine'],
                    },
                },
                team,
                'http://localhost:8000',
                WebhookType.Slack,
                tokenUserPropString
            )

            expect(text).toBe('["pineapple","broccoli","aubergine"]')
            expect(markdown).toBe('["pineapple","broccoli","aubergine"]')
        })

        test('user name (alias for person name)', () => {
            const tokenUserName = ['user', 'name']

            const [text, markdown] = getValueOfToken(
                action,
                event,
                team,
                'http://localhost:8000',
                WebhookType.Teams,
                tokenUserName
            )

            expect(text).toBe('WALL-E')
            expect(markdown).toBe('[WALL-E](http://localhost:8000/person/WALL-E)')
        })

        test('user prop (actually event prop)', () => {
            const tokenUserPropString = ['user', 'browser']

            const [text, markdown] = getValueOfToken(
                action,
                event,
                team,
                'http://localhost:8000',
                WebhookType.Teams,
                tokenUserPropString
            )

            expect(text).toBe('Chrome')
            expect(markdown).toBe('Chrome')
        })

        test('user prop but missing', () => {
            const tokenUserPropMissing = ['user', 'missing_property']

            const [text, markdown] = getValueOfToken(
                action,
                event,
                team,
                'http://localhost:8000',
                WebhookType.Teams,
                tokenUserPropMissing
            )

            expect(text).toBe('undefined')
            expect(markdown).toBe('undefined')
        })

        test('escapes slack', () => {
            const [text, markdown] = getValueOfToken(
                action,
                { ...event, eventUuid: '**>)', event: 'text><new link' },
                team,
                'http://localhost:8000',
                WebhookType.Slack,
                ['event']
            )

            expect(text).toBe('text&gt;&lt;new link')
            expect(markdown).toBe(
                '<http://localhost:8000/events/**%3E)/2021-10-31T00%3A44%3A00.000Z|text&gt;&lt;new link>'
            )
        })

        test('escapes teams', () => {
            const [text, markdown] = getValueOfToken(
                action,
                { ...event, eventUuid: '**)', event: 'text](yes!), [new link' },
                team,
                'http://localhost:8000',
                WebhookType.Teams,
                ['event']
            )

            expect(text).toBe('text\\]\\(yes\\!\\), \\[new link')
            expect(markdown).toBe(
                '[text\\]\\(yes\\!\\), \\[new link](http://localhost:8000/events/\\*\\*\\)/2021-10-31T00%3A44%3A00.000Z)'
            )
        })
    })

    describe('getFormattedMessage', () => {
        const event = {
            distinctId: '2',
            properties: { $browser: 'Chrome', page_title: 'Pricing', 'with space': 'yes sir' },
        } as unknown as PostIngestionEvent
        const team = { person_display_name_properties: null } as Team

        test('custom format', () => {
            const action = {
                id: 1,
                name: 'action1',
                slack_message_format:
                    '[user.name] from [user.browser] on [event.properties.page_title] page with [event.properties.fruit], [event.properties.with space]',
            } as Action

            const [text, markdown] = getFormattedMessage(
                action,
                event,
                team,
                'https://localhost:8000',
                WebhookType.Slack
            )
            expect(text).toBe('2 from Chrome on Pricing page with undefined, yes sir')
            expect(markdown).toBe(
                '<https://localhost:8000/person/2|2> from Chrome on Pricing page with undefined, yes sir'
            )
        })

        test('default format', () => {
            const action = { id: 1, name: 'action1', slack_message_format: '' } as Action

            const [text, markdown] = getFormattedMessage(
                action,
                event,
                team,
                'https://localhost:8000',
                WebhookType.Slack
            )
            expect(text).toBe('action1 was triggered by 2')
            expect(markdown).toBe(
                '<https://localhost:8000/action/1|action1> was triggered by <https://localhost:8000/person/2|2>'
            )
        })

        test('not quite correct format', () => {
            const action = {
                id: 1,
                name: 'action1',
                slack_message_format: '[user.name] did thing from browser [user.brauzer]',
            } as Action

            const [text, markdown] = getFormattedMessage(
                action,
                event,
                team,
                'https://localhost:8000',
                WebhookType.Slack
            )
            expect(text).toBe('2 did thing from browser undefined')
            expect(markdown).toBe('<https://localhost:8000/person/2|2> did thing from browser undefined')
        })
    })

    describe('postRestHook', () => {
        let hookCommander: HookCommander
        let hook: Hook
        const action = {
            id: 1,
            name: 'action1',
            // slack_message_format: '[user.name] did thing from browser [user.brauzer]',
        } as Action
        const team = { person_display_name_properties: null } as Team

        beforeEach(() => {
            hook = {
                id: 'id',
                team_id: 1,
                user_id: 1,
                resource_id: 1,
                event: 'foo',
                target: 'https://example.com/',
                created: new Date().toISOString(),
                updated: new Date().toISOString(),
            }
            hookCommander = new HookCommander(
                {} as any,
                {} as any,
                {} as any,
                { enqueueIfEnabledForTeam: async () => Promise.resolve(false) },
                { queueError: () => Promise.resolve(), queueMetric: () => Promise.resolve() } as unknown as AppMetrics,
                20000
            )
        })

        test('person = undefined', async () => {
            await hookCommander.postWebhook({ event: 'foo' } as any, action, team, hook)

            expect(fetch).toHaveBeenCalledWith('https://example.com/', {
                body: JSON.stringify(
                    {
                        hook: {
                            id: 'id',
                            event: 'foo',
                            target: 'https://example.com/',
                        },
                        data: {
                            event: 'foo',
                            person: {}, // person becomes empty object if undefined
                        },
                    },
                    undefined,
                    4
                ),
                headers: { 'Content-Type': 'application/json' },
                method: 'POST',
                timeout: 20000,
            })
        })

        test('person data from the event', async () => {
            const now = new Date().toISOString()
            const uuid = new UUIDT().toString()
            await hookCommander.postWebhook(
                {
                    event: 'foo',
                    teamId: hook.team_id,
                    person_id: uuid,
                    person_properties: { foo: 'bar' },
                    person_created_at: DateTime.fromISO(now).toUTC(),
                } as any,
                action,
                team,
                hook
            )
            expect(fetch).toHaveBeenCalledWith('https://example.com/', {
                body: JSON.stringify(
                    {
                        hook: {
                            id: 'id',
                            event: 'foo',
                            target: 'https://example.com/',
                        },
                        data: {
                            event: 'foo',
                            teamId: hook.team_id,
                            person: {
                                uuid: uuid,
                                properties: { foo: 'bar' },
                                created_at: now,
                            },
                        },
                    },
                    undefined,
                    4
                ),
                headers: { 'Content-Type': 'application/json' },
                method: 'POST',
                timeout: 20000,
            })
        })

        test('private IP hook forbidden in prod', async () => {
            process.env.NODE_ENV = 'production'

            await expect(
                hookCommander.postWebhook({ event: 'foo' } as any, action, team, {
                    ...hook,
                    target: 'http://127.0.0.1',
                })
            ).rejects.toThrow(new FetchError('Internal hostname', 'posthog-host-guard'))
        })
    })
})
