import { Badge, Button, FieldContent, FieldDescription, FieldTitle, Separator } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { QuillSettingsSubsection } from '../QuillSettingsSubsection/QuillSettingsSubsection'
import { QuillTeamsChannelPair, QuillTeamsChannelRow } from '../QuillTeamsChannelRow/QuillTeamsChannelRow'

export function QuillTeamsSection({
    teamsConnected,
    channelPairs,
    removingChannelId,
    adminRestrictionReason,
    showAddRow,
    addRow,
    onConnect,
    onDisconnect,
    onRemovePair,
    onShowAddRow,
}: {
    teamsConnected: boolean
    channelPairs: QuillTeamsChannelPair[]
    removingChannelId: string | null
    adminRestrictionReason: string | null
    showAddRow: boolean
    addRow: React.ReactNode
    onConnect: () => void
    onDisconnect: () => void
    onRemovePair: (channelId: string) => void
    onShowAddRow: () => void
}): JSX.Element {
    return (
        <QuillSettingsSubsection
            title="Microsoft Teams"
            description={
                <>
                    Connect the SupportHog bot to Microsoft Teams to create and manage support tickets from Teams
                    channel messages and @mentions.{' '}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={<LinkPrimitive to="https://posthog.com/docs/support/teams" target="_blank" />}
                    >
                        Docs
                    </Button>
                </>
            }
        >
            <div className="flex flex-col gap-2">
                <FieldContent>
                    <FieldTitle>Connection</FieldTitle>
                    <FieldDescription>
                        Connect your Microsoft Teams tenant to enable support ticket creation from channel messages and
                        @mentions. Requires a Teams admin to authorize the SupportHog app.
                    </FieldDescription>
                </FieldContent>
                {!teamsConnected && (
                    <div>
                        <Button variant="primary" disabledReason={adminRestrictionReason} onClick={onConnect}>
                            Connect Microsoft Teams
                        </Button>
                    </div>
                )}
            </div>
            {teamsConnected && (
                <>
                    <Separator />
                    <div className="flex flex-col gap-2">
                        <FieldContent>
                            <FieldTitle>Support channels</FieldTitle>
                            <FieldDescription>
                                Messages posted in these channels will automatically create support tickets. Thread
                                replies become ticket messages.
                            </FieldDescription>
                        </FieldContent>
                        {channelPairs.length > 0 && (
                            <div className="flex flex-col gap-2">
                                {channelPairs.map((pair) => (
                                    <QuillTeamsChannelRow
                                        key={pair.channel_id}
                                        pair={pair}
                                        onRemove={() => onRemovePair(pair.channel_id)}
                                        isLoading={removingChannelId === pair.channel_id}
                                        adminRestrictionReason={adminRestrictionReason}
                                    />
                                ))}
                            </div>
                        )}
                        {showAddRow ? (
                            addRow
                        ) : (
                            <div>
                                <Button
                                    variant="outline"
                                    onClick={onShowAddRow}
                                    disabledReason={adminRestrictionReason || undefined}
                                >
                                    Add Teams channel
                                </Button>
                            </div>
                        )}
                    </div>
                    <Separator />
                    <div className="flex items-center justify-between gap-4">
                        <FieldContent>
                            <FieldTitle>Bot mention</FieldTitle>
                            <FieldDescription>
                                Users can @mention the bot in any channel to create a support ticket.
                            </FieldDescription>
                        </FieldContent>
                        <Badge variant="success">Active</Badge>
                    </div>
                    <Separator />
                    <div className="flex justify-end">
                        <Button
                            variant="destructive-outline"
                            disabledReason={adminRestrictionReason}
                            onClick={onDisconnect}
                        >
                            Disconnect Microsoft Teams
                        </Button>
                    </div>
                </>
            )}
        </QuillSettingsSubsection>
    )
}
