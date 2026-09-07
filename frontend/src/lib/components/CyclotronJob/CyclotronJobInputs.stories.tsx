import { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'
import { mockBasicUser, mockSlackChannels } from '~/test/mocks'
import { CyclotronJobInputSchemaType, IntegrationType } from '~/types'

import { CyclotronJobInputs } from './CyclotronJobInputs'

// Mirrors nodejs/src/cdp/templates/_destinations/slack/slack.template.ts, trimmed to the inputs
// that carry scopes. `requiredScopes` on the connection is a hard requirement; on a field it is
// the scope only that field needs.
const SLACK_INPUTS_SCHEMA: CyclotronJobInputSchemaType[] = [
    {
        key: 'slack_workspace',
        type: 'integration',
        integration: 'slack',
        label: 'Slack workspace',
        requiredScopes: 'chat:write',
        required: true,
    },
    {
        key: 'channel',
        type: 'integration_field',
        integration_key: 'slack_workspace',
        integration_field: 'slack_channel',
        requiredScopes: 'channels:read groups:read',
        label: 'Channel to post to',
        required: true,
    },
    {
        key: 'icon_emoji',
        type: 'string',
        label: 'Emoji icon',
        integration_key: 'slack_workspace',
        requiredScopes: 'chat:write.customize',
        required: false,
    },
    {
        key: 'username',
        type: 'string',
        label: 'Bot name',
        integration_key: 'slack_workspace',
        requiredScopes: 'chat:write.customize',
        required: false,
    },
]

const SLACK_INPUTS = {
    slack_workspace: { value: 1 },
    channel: { value: 'C1' },
    icon_emoji: { value: ':hedgehog:' },
    username: { value: 'PostHog' },
}

const EVERY_SCOPE = 'channels:read groups:read chat:write chat:write.customize'

const slackIntegration = (scope: string): IntegrationType => ({
    id: 1,
    kind: 'slack',
    display_name: 'PostHog HQ',
    icon_url: '',
    config: { scope, team: { id: '123', name: 'PostHog' } },
    created_at: '2024-01-01T00:00:00Z',
    created_by: mockBasicUser,
})

type StoryArgs = { scope: string }

const meta: Meta<StoryArgs> = {
    title: 'Components/Cyclotron job inputs',
    parameters: { layout: 'padded', viewMode: 'story' },
    render: ({ scope }) => {
        useStorybookMocks({
            get: {
                '/api/environments/:team_id/integrations': {
                    results: [slackIntegration(scope)],
                },
                '/api/environments/:team_id/integrations/:intId/channels': {
                    // is_member, so the picker doesn't add an unrelated "app is not in this channel" warning
                    channels: mockSlackChannels.map((channel) => ({ ...channel, is_member: true })),
                },
            },
        })
        return (
            <div className="max-w-2xl">
                <CyclotronJobInputs
                    configuration={{ inputs_schema: SLACK_INPUTS_SCHEMA, inputs: SLACK_INPUTS }}
                    showSource={false}
                    sampleGlobalsWithInputs={null}
                />
            </div>
        )
    },
}
export default meta

type Story = StoryObj<StoryArgs>

// Nothing to say: no banner on the connection, no hint on any field.
export const SlackFullyScoped: Story = {
    args: { scope: EVERY_SCOPE },
}

// Without chat:write the destination cannot post at all, so the connection itself errors and
// offers a reconnect.
export const SlackMissingRequiredScope: Story = {
    args: { scope: 'channels:read groups:read chat:write.customize' },
}

// The destination posts fine, so the connection stays clean. Only the two fields that need
// chat:write.customize say what they are missing.
export const SlackMissingOptionalScope: Story = {
    args: { scope: 'channels:read groups:read chat:write' },
}
