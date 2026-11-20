import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import { SlackChannelType } from '~/types'

export interface SlackChannelOption {
    key: string
    label: string
}

export function slackChannelOptions(slackChannels: SlackChannelType[]): SlackChannelOption[] {
    return slackChannels.map((c) => ({
        key: c.id,
        label: `#${c.name ?? c.id}`,
    }))
}

export function confirmRemoveSlackBot(disconnectSlack: () => void): void {
    LemonDialog.open({
        title: 'Remove SupportHog bot?',
        description: 'This will stop creating tickets from Slack messages. Existing tickets will not be affected.',
        primaryButton: {
            status: 'danger',
            children: 'Remove',
            onClick: disconnectSlack,
        },
        secondaryButton: { children: 'Cancel' },
    })
}
