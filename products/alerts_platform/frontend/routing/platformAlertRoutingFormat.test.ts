import type { AlertReceiverApi } from '../generated/api.schemas'
import {
    EMPTY_RECEIVER_FORM,
    ReceiverForm,
    receiverDestinationBody,
    receiverFormErrors,
    routeFormErrors,
} from './platformAlertRoutingFormat'

const WEBHOOK_RECEIVER: AlertReceiverApi = {
    id: 'receiver-1',
    name: 'Infra',
    type: 'webhook',
    enabled: true,
    route_count: 0,
    webhook_url: 'https://example.com',
}
const SLACK_RECEIVER: AlertReceiverApi = {
    ...WEBHOOK_RECEIVER,
    type: 'slack',
    webhook_url: undefined,
    slack_workspace_id: 7,
    slack_channel_id: 'C1',
    slack_channel_name: 'alerts',
}
const PAGERDUTY_RECEIVER: AlertReceiverApi = {
    ...WEBHOOK_RECEIVER,
    type: 'pagerduty',
    webhook_url: undefined,
    pagerduty_routing_key: '••••c3d4',
    pagerduty_severity: 'critical',
    pagerduty_region: 'us',
}
const PAGERDUTY_FORM: ReceiverForm = { ...EMPTY_RECEIVER_FORM, name: 'Pager', type: 'pagerduty' }

describe('receiverDestinationBody', () => {
    test.each<[string, ReceiverForm, AlertReceiverApi | null, ReturnType<typeof receiverDestinationBody>]>([
        [
            'an edit with a blank URL keeps the stored webhook',
            {
                ...EMPTY_RECEIVER_FORM,
                name: 'Infra',
                type: 'webhook',
                slackWorkspaceId: null,
                slackChannel: null,
                webhookUrl: '',
            },
            WEBHOOK_RECEIVER,
            null,
        ],
        [
            'an edit to another type sends the new destination',
            {
                ...EMPTY_RECEIVER_FORM,
                name: 'Infra',
                type: 'teams',
                slackWorkspaceId: null,
                slackChannel: null,
                webhookUrl: ' https://example.com/teams ',
            },
            WEBHOOK_RECEIVER,
            { type: 'teams', webhook_url: 'https://example.com/teams' },
        ],
        [
            'an edit that keeps the Slack channel sends nothing',
            {
                ...EMPTY_RECEIVER_FORM,
                name: 'Infra',
                type: 'slack',
                slackWorkspaceId: 7,
                slackChannel: 'C1|#alerts',
                webhookUrl: '',
            },
            SLACK_RECEIVER,
            null,
        ],
        [
            'a new Slack receiver splits the picker value',
            {
                ...EMPTY_RECEIVER_FORM,
                name: 'Infra',
                type: 'slack',
                slackWorkspaceId: 7,
                slackChannel: 'C2|#on-call',
                webhookUrl: '',
            },
            null,
            { type: 'slack', slack_workspace_id: 7, slack_channel_id: 'C2', slack_channel_name: 'on-call' },
        ],
        ['an edit with a blank key keeps the stored PagerDuty key', PAGERDUTY_FORM, PAGERDUTY_RECEIVER, null],
        [
            'a new PagerDuty receiver sends the key, severity and region',
            { ...PAGERDUTY_FORM, pagerdutyRoutingKey: ' a1b2 ', pagerdutySeverity: 'warning', pagerdutyRegion: 'eu' },
            null,
            {
                type: 'pagerduty',
                pagerduty_routing_key: 'a1b2',
                pagerduty_severity: 'warning',
                pagerduty_region: 'eu',
            },
        ],
    ])('%s', (_name, form, editing, expected) => {
        expect(receiverDestinationBody(form, 7, editing)).toEqual(expected)
    })

    // The API replaces the whole destination, so a severity change without the key would save an empty key.
    test.each<[string, ReceiverForm, string | undefined]>([
        ['a blank key with the stored severity', PAGERDUTY_FORM, undefined],
        [
            'a blank key with a new severity',
            { ...PAGERDUTY_FORM, pagerdutySeverity: 'info' },
            'Enter the integration key again to change the severity or region',
        ],
    ])('editing a PagerDuty receiver: %s', (_name, form, expected) => {
        expect(receiverFormErrors(form, PAGERDUTY_RECEIVER).pagerdutyRoutingKey).toEqual(expected)
    })

    // The modal hides the event options for PagerDuty, so an error on them could not be seen or fixed.
    test.each<[string, 'slack' | 'pagerduty', string | undefined]>([
        ['a chat receiver with no events', 'slack', 'Choose at least one event'],
        ['a PagerDuty receiver with no events', 'pagerduty', undefined],
    ])('route form: %s', (_name, receiverType, expected) => {
        expect(routeFormErrors({ receiverId: 'r1', matchers: [], eventKinds: [] }, receiverType).eventKinds).toEqual(
            expected
        )
    })
})
