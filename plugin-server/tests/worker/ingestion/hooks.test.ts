import { PluginEvent } from '@posthog/plugin-scaffold'

import { Action, Person } from '../../../src/types'
import {
    determineWebhookType,
    getActionDetails,
    getFormattedMessage,
    getTokens,
    getUserDetails,
    getValueOfToken,
    WebhookType,
} from '../../../src/worker/ingestion/hooks'

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
    const event = { distinct_id: 2 } as unknown as PluginEvent
    const person = { properties: { email: 'test@posthog.com' } } as unknown as Person

    test('Slack', () => {
        const [userDetails, userDetailsMarkdown] = getUserDetails(
            event,
            person,
            'http://localhost:8000',
            WebhookType.Slack
        )

        expect(userDetails).toBe('test@posthog.com')
        expect(userDetailsMarkdown).toBe('<http://localhost:8000/person/2|test@posthog.com>')
    })

    test('Teams', () => {
        const [userDetails, userDetailsMarkdown] = getUserDetails(
            event,
            person,
            'http://localhost:8000',
            WebhookType.Teams
        )

        expect(userDetails).toBe('test@posthog.com')
        expect(userDetailsMarkdown).toBe('[test@posthog.com](http://localhost:8000/person/2)')
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
    const event = { distinct_id: 2, properties: { $browser: 'Chrome' } } as unknown as PluginEvent
    const person = {} as Person

    test('user name', () => {
        const tokenUserName = ['user', 'name']

        const [text, markdown] = getValueOfToken(
            action,
            event,
            person,
            'http://localhost:8000',
            WebhookType.Teams,
            tokenUserName
        )

        expect(text).toBe('2')
        expect(markdown).toBe('[2](http://localhost:8000/person/2)')
    })

    test('user prop', () => {
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
        distinct_id: 2,
        properties: { $browser: 'Chrome', page_title: 'Pricing' },
    } as unknown as PluginEvent
    const person = {} as Person

    test('custom format', () => {
        const action = {
            id: 1,
            name: 'action1',
            slack_message_format:
                '[user.name] from [user.browser] on [event.properties.page_title] page with [event.properties.fruit]',
        } as Action

        const [text, markdown] = getFormattedMessage(action, event, person, 'https://localhost:8000', WebhookType.Slack)
        expect(text).toBe('2 from Chrome on Pricing page with undefined')
        expect(markdown).toBe('<https://localhost:8000/person/2|2> from Chrome on Pricing page with undefined')
    })

    test('default format', () => {
        const action = { id: 1, name: 'action1', slack_message_format: '' } as Action

        const [text, markdown] = getFormattedMessage(action, event, person, 'https://localhost:8000', WebhookType.Slack)
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

        const [text, markdown] = getFormattedMessage(action, event, person, 'https://localhost:8000', WebhookType.Slack)
        expect(text).toBe('2 did thing from browser undefined')
        expect(markdown).toBe('<https://localhost:8000/person/2|2> did thing from browser undefined')
    })
})
