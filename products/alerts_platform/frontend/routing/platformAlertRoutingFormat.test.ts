import type { AlertReceiverApi } from '../generated/api.schemas'
import { ReceiverForm, receiverDestinationBody } from './platformAlertRoutingFormat'

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

describe('receiverDestinationBody', () => {
    test.each<[string, ReceiverForm, AlertReceiverApi | null, ReturnType<typeof receiverDestinationBody>]>([
        [
            'an edit with a blank URL keeps the stored webhook',
            { name: 'Infra', type: 'webhook', slackWorkspaceId: null, slackChannel: null, webhookUrl: '' },
            WEBHOOK_RECEIVER,
            null,
        ],
        [
            'an edit to another type sends the new destination',
            {
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
            { name: 'Infra', type: 'slack', slackWorkspaceId: 7, slackChannel: 'C1|#alerts', webhookUrl: '' },
            SLACK_RECEIVER,
            null,
        ],
        [
            'a new Slack receiver splits the picker value',
            { name: 'Infra', type: 'slack', slackWorkspaceId: 7, slackChannel: 'C2|#on-call', webhookUrl: '' },
            null,
            { type: 'slack', slack_workspace_id: 7, slack_channel_id: 'C2', slack_channel_name: 'on-call' },
        ],
    ])('%s', (_name, form, editing, expected) => {
        expect(receiverDestinationBody(form, 7, editing)).toEqual(expected)
    })
})
