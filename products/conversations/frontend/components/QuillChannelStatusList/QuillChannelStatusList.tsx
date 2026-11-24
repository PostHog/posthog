import { Badge, Button, Card, CardContent, Item, ItemActions, ItemContent, ItemTitle } from '@posthog/quill'

import { type ChannelTabKey } from '../../scenes/settings/openChannelSettings'

export function QuillChannelStatusList({
    channels,
    onOpenChannel,
}: {
    channels: { key: ChannelTabKey; label: string; on: boolean }[]
    onOpenChannel: (channel: ChannelTabKey) => void
}): JSX.Element {
    return (
        <Card size="sm" className="max-w-200">
            <CardContent className="flex flex-col divide-y">
                {channels.map((channel) => (
                    <Item key={channel.key} size="sm" className="px-0">
                        <ItemContent>
                            <ItemTitle className="flex items-center gap-2">
                                {channel.label}
                                <Badge variant={channel.on ? 'success' : 'default'}>{channel.on ? 'On' : 'Off'}</Badge>
                            </ItemTitle>
                        </ItemContent>
                        <ItemActions>
                            <Button
                                variant="outline"
                                onClick={() => onOpenChannel(channel.key)}
                                data-attr={`support-general-channel-${channel.key}`}
                            >
                                {channel.on ? 'Manage' : 'Set up'}
                            </Button>
                        </ItemActions>
                    </Item>
                ))}
            </CardContent>
        </Card>
    )
}
