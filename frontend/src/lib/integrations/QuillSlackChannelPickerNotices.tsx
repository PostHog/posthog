import { useActions, useValues } from 'kea'

import { Button, Item, ItemActions, ItemContent, ItemDescription, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import { IntegrationType } from '~/types'

import { QuillSlackIntegrationInactiveBanner } from './QuillSlackIntegrationInactiveBanner'
import { slackChannelId } from './slackChannel'
import { slackIntegrationLogic } from './slackIntegrationLogic'

export function QuillSlackChannelPickerNotices({
    integration,
    values,
    showUnselectedSearchError,
}: {
    integration: IntegrationType
    values: string[]
    showUnselectedSearchError: boolean
}): JSX.Element {
    const logic = slackIntegrationLogic({ id: integration.id })
    const {
        allSlackChannels,
        allSlackChannelsLoading,
        slackChannelByIdLoading,
        isMemberOfSlackChannel,
        isPrivateChannelWithoutAccess,
        slackIntegrationInactiveMessage,
    } = useValues(logic)
    const { recheckSlackChannelMembership } = useActions(logic)

    const channelsMissingTheApp = values.filter((value) => isMemberOfSlackChannel(value) === false)
    const showPrivateChannelWarning = values.some((value) => isPrivateChannelWithoutAccess(value))

    return (
        <>
            {showUnselectedSearchError ? (
                <Text size="xs" variant="destructive" render={<p className="m-0" role="alert" />}>
                    No channel selected. Pick one from the list.
                </Text>
            ) : null}

            {slackIntegrationInactiveMessage ? (
                <QuillSlackIntegrationInactiveBanner message={slackIntegrationInactiveMessage} />
            ) : null}

            {allSlackChannels?.has_more && !allSlackChannelsLoading ? (
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    Only the first page of channels is shown. Type to search for a specific channel.
                </Text>
            ) : null}

            {channelsMissingTheApp.length ? (
                <Item tone="info" size="sm" className="flex-wrap">
                    <ItemContent>
                        <ItemDescription>
                            {values.length > 1
                                ? 'The PostHog Slack app is not in every selected channel. '
                                : 'The PostHog Slack app is not in this channel. '}
                            Invite it with <code>/invite @PostHog</code> in Slack, then check again.{' '}
                            <Button
                                variant="link"
                                size="inline"
                                nativeButton={false}
                                render={<LinkPrimitive to="https://posthog.com/docs/webhooks/slack" target="_blank" />}
                            >
                                See the docs for more information
                            </Button>
                        </ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <Button
                            variant="outline"
                            onClick={() => recheckSlackChannelMembership(channelsMissingTheApp.map(slackChannelId))}
                            loading={slackChannelByIdLoading}
                        >
                            Check again
                        </Button>
                    </ItemActions>
                </Item>
            ) : showPrivateChannelWarning ? (
                <Item tone="info" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            {values.length > 1 ? 'One or more selected Slack channels are' : 'This Slack channel is'}{' '}
                            private. Ask <ProfilePicture user={integration.created_by} showName size="sm" /> or connect
                            your own Slack account to configure private channels.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            ) : null}
        </>
    )
}
