import { DateTime } from 'luxon'
import * as fetch from 'node-fetch'

import { Action, Person, PreIngestionEvent } from '../../../src/types'
import { UUIDT } from '../../../src/utils/utils'
import {
    determineWebhookType,
    getActionDetails,
    getFormattedMessage,
    getTokens,
    getUserDetails,
    getValueOfToken,
    HookCommander,
    WebhookType,
} from '../../../src/worker/ingestion/hooks'
import { Hook } from './../../../src/types'

describe('hooks', () => {
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

    describe('getUserDetails', () => {
        const event = { distinctId: 'WALL-E' } as unknown as PreIngestionEvent
        const person = { properties: { email: 'test@posthog.com' } } as unknown as Person

        test('Slack', () => {
            const [userDetails, userDetailsMarkdown] = getUserDetails(
                event,
                person,
                'http://localhost:8000',
                WebhookType.Slack
            )

            expect(userDetails).toBe('test@posthog.com')
            expect(userDetailsMarkdown).toBe('<http://localhost:8000/person/WALL-E|test@posthog.com>')
        })

        test('Teams', () => {
            const [userDetails, userDetailsMarkdown] = getUserDetails(
                event,
                person,
                'http://localhost:8000',
                WebhookType.Teams
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
    })

    describe('getValueOfToken', () => {
        const action = { id: 1, name: 'action1' } as Action
        const event = { distinctId: 'WALL-E', properties: { $browser: 'Chrome' } } as unknown as PreIngestionEvent
        const person = { properties: { enjoys_broccoli_on_pizza: false } } as unknown as Person

        test('person with just distinct ID', () => {
            const tokenUserName = ['person']

            const [text, markdown] = getValueOfToken(
                action,
                event,
                person,
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
                event,
                { ...person, properties: { ...person.properties, email: 'wall-e@buynlarge.com' } },
                'http://localhost:8000',
                WebhookType.Teams,
                tokenUserName
            )

            expect(text).toBe('wall-e@buynlarge.com')
            expect(markdown).toBe('[wall-e@buynlarge.com](http://localhost:8000/person/WALL-E)')
        })

        test('person prop', () => {
            const tokenUserPropString = ['person', 'properties', 'enjoys_broccoli_on_pizza']

            const [text, markdown] = getValueOfToken(
                action,
                event,
                person,
                'http://localhost:8000',
                WebhookType.Teams,
                tokenUserPropString
            )

            expect(text).toBe('false')
            expect(markdown).toBe('false')
        })

        test('user name (alias for person name)', () => {
            const tokenUserName = ['user', 'name']

            const [text, markdown] = getValueOfToken(
                action,
                event,
                person,
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
                person,
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
                person,
                'http://localhost:8000',
                WebhookType.Teams,
                tokenUserPropMissing
            )

            expect(text).toBe('undefined')
            expect(markdown).toBe('undefined')
        })
    })

    describe('getFormattedMessage', () => {
        const event = {
            distinctId: 2,
            properties: { $browser: 'Chrome', page_title: 'Pricing' },
        } as unknown as PreIngestionEvent
        const person = {} as Person

        test('custom format', () => {
            const action = {
                id: 1,
                name: 'action1',
                slack_message_format:
                    '[user.name] from [user.browser] on [event.properties.page_title] page with [event.properties.fruit]',
            } as Action

            const [text, markdown] = getFormattedMessage(
                action,
                event,
                person,
                'https://localhost:8000',
                WebhookType.Slack
            )
            expect(text).toBe('2 from Chrome on Pricing page with undefined')
            expect(markdown).toBe('<https://localhost:8000/person/2|2> from Chrome on Pricing page with undefined')
        })

        test('default format', () => {
            const action = { id: 1, name: 'action1', slack_message_format: '' } as Action

            const [text, markdown] = getFormattedMessage(
                action,
                event,
                person,
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
                person,
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

        beforeEach(() => {
            hookCommander = new HookCommander({} as any, {} as any, {} as any)
            hook = {
                id: 'id',
                team_id: 2,
                user_id: 1,
                resource_id: 1,
                event: 'foo',
                target: 'foo.bar',
                created: new Date().toISOString(),
                updated: new Date().toISOString(),
            }
        })

        test('person = undefined', async () => {
            await hookCommander.postRestHook(hook, { event: 'foo' } as any, undefined)

            expect(fetch).toHaveBeenCalledWith('foo.bar', {
                body: JSON.stringify(
                    {
                        hook: {
                            id: 'id',
                            event: 'foo',
                            target: 'foo.bar',
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
            })
        })

        test('person instanceof CachedPersonData', async () => {
            const now = new Date().toISOString()
            const uuid = new UUIDT().toString()
            const person = {
                uuid: uuid,
                properties: { foo: 'bar' },
                team_id: 1,
                id: 1,
                created_at_iso: now,
            }
            await hookCommander.postRestHook(hook, { event: 'foo' } as any, person)
            expect(fetch).toHaveBeenCalledWith('foo.bar', {
                body: JSON.stringify(
                    {
                        hook: {
                            id: 'id',
                            event: 'foo',
                            target: 'foo.bar',
                        },
                        data: {
                            event: 'foo',
                            person: {
                                uuid: uuid,
                                properties: { foo: 'bar' },
                                team_id: 1,
                                id: 1,
                                created_at: now,
                            },
                        },
                    },
                    undefined,
                    4
                ),
                headers: { 'Content-Type': 'application/json' },
                method: 'POST',
            })
        })

        test('person instanceof Person', async () => {
            const now = DateTime.now()
            const uuid = new UUIDT().toString()
            const person = {
                uuid: uuid,
                properties: { foo: 'bar' },
                team_id: 1,
                id: 1,
                created_at: now,
                is_user_id: 1,
                is_identified: false,
                properties_last_updated_at: {},
                properties_last_operation: {},
                version: 15,
            }
            await hookCommander.postRestHook(hook, { event: 'foo' } as any, person)
            expect(fetch).toHaveBeenCalledWith('foo.bar', {
                body: JSON.stringify(
                    {
                        hook: {
                            id: 'id',
                            event: 'foo',
                            target: 'foo.bar',
                        },
                        data: {
                            event: 'foo',
                            person: {
                                uuid: uuid,
                                properties: { foo: 'bar' },
                                team_id: 1,
                                id: 1,
                                created_at: now.toISO(),
                            },
                        },
                    },
                    undefined,
                    4
                ),
                headers: { 'Content-Type': 'application/json' },
                method: 'POST',
            })
        })
    })
})
