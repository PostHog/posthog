import {
    LemonBanner,
    LemonButton,
    LemonInputSelect,
    LemonInputSelectOption,
    Link,
    ProfilePicture,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconSlackExternal } from 'lib/lemon-ui/icons'
import { useEffect, useMemo, useState } from 'react'

import { IntegrationType, SlackChannelType } from '~/types'

import { slackIntegrationLogic } from './slackIntegrationLogic'

export type SlackChannelPickerProps = {
    integration: IntegrationType
    value?: string
    onChange?: (value: string | null) => void
    disabled?: boolean
}

export function SlackChannelPicker({ onChange, value, integration, disabled }: SlackChannelPickerProps): JSX.Element {
    const {
        slackChannels,
        allSlackChannelsLoading,
        slackChannelByIdLoading,
        isMemberOfSlackChannel,
        isPrivateChannelWithoutAccess,
    } = useValues(slackIntegrationLogic({ id: integration.id }))
    const { loadAllSlackChannels, loadSlackChannelById } = useActions(slackIntegrationLogic({ id: integration.id }))
    const [currentInputValue, setCurrentInputValue] = useState<string | null>(null)

    const getSlackChannelOptions = useMemo(
        () =>
            (slackChannels?: SlackChannelType[] | null): LemonInputSelectOption[] | null => {
                return slackChannels
                    ? slackChannels.map((x) => ({
                          key: `${x.id}|#${x.name}`,
                          labelComponent: (
                              <span className="flex items-center">
                                  <span>{x.is_private ? `🔒${x.name}` : `#${x.name}`}</span>
                                  <span>{x.is_ext_shared ? <IconSlackExternal className="ml-2" /> : null}</span>
                              </span>
                          ),
                          label: `${x.id} #${x.name}`,
                      }))
                    : null
            },
        [slackChannels]
    )

    // If slackChannels aren't loaded, make sure we display only the channel name and not the actual underlying value
    const slackChannelOptions = useMemo(() => {
        const channels = getSlackChannelOptions(slackChannels)
        return channels?.filter((x) => {
            const [id, name] = x.key.split('|#')
            return name !== 'PRIVATE_CHANNEL_WITHOUT_ACCESS' || id === currentInputValue
        })
    }, [slackChannels, value])
    const showSlackMembershipWarning = value && isMemberOfSlackChannel(value) === false

    // Sometimes the parent will only store the channel ID and not the name, so we need to handle that

    const modifiedValue = useMemo(() => {
        if (value?.split('|').length === 1) {
            const channel = slackChannels.find((x: SlackChannelType) => x.id === value)

            if (channel) {
                return `${channel.id}|#${channel.name}`
            }
        }

        return value
    }, [value, slackChannels])

    useEffect(() => {
        if (!disabled) {
            loadAllSlackChannels()
        }
    }, [loadAllSlackChannels, disabled])

    return (
        <>
            <LemonInputSelect
                onChange={(val) => onChange?.(val[0] ?? null)}
                onInputChange={(val) => {
                    if (val) {
                        loadSlackChannelById(val)
                        setCurrentInputValue(val)
                    }
                }}
                value={modifiedValue ? [modifiedValue] : []}
                onFocus={() => !slackChannels.length && !allSlackChannelsLoading && loadAllSlackChannels()}
                disabled={disabled}
                mode="single"
                data-attr="select-slack-channel"
                placeholder="Select a channel..."
                emptyStateComponent={
                    <p className="text-secondary italic p-1">
                        No channels found. Make sure the PostHog Slack App is installed in the channel.{' '}
                        <Link to="https://posthog.com/docs/cdp/destinations/slack" target="_blank">
                            See the docs for more information.
                        </Link>
                    </p>
                }
                options={
                    slackChannelOptions ??
                    (modifiedValue
                        ? [
                              {
                                  key: modifiedValue,
                                  label: modifiedValue?.split('|')[1] ?? modifiedValue,
                              },
                          ]
                        : [])
                }
                loading={allSlackChannelsLoading || slackChannelByIdLoading}
            />

            {showSlackMembershipWarning ? (
                <LemonBanner type="info">
                    <div className="flex gap-2 items-center">
                        <span>
                            The PostHog Slack App is not in this channel. Please add it to the channel otherwise
                            Subscriptions will fail to be delivered.{' '}
                            <Link to="https://posthog.com/docs/webhooks/slack" target="_blank">
                                See the Docs for more information
                            </Link>
                        </span>
                        <LemonButton type="secondary" onClick={loadAllSlackChannels} loading={allSlackChannelsLoading}>
                            Check again
                        </LemonButton>
                    </div>
                </LemonBanner>
            ) : isPrivateChannelWithoutAccess(value ?? '') ? (
                <LemonBanner type="info">
                    This is a private slack channel. Ask{' '}
                    <ProfilePicture user={integration.created_by} showName size="md" /> or connect your own Slack
                    account to configure private channels.
                </LemonBanner>
            ) : null}
        </>
    )
}
