import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import {
    LemonBanner,
    LemonButton,
    LemonInputSelect,
    LemonInputSelectOption,
    Link,
    ProfilePicture,
} from '@posthog/lemon-ui'

import { usePeriodicRerender } from 'lib/hooks/usePeriodicRerender'
import { IconSlackExternal } from 'lib/lemon-ui/icons'

import { IntegrationType, SlackChannelType } from '~/types'

import { slackIntegrationLogic } from './slackIntegrationLogic'

const getSlackChannelOptions = (slackChannels?: SlackChannelType[] | null): LemonInputSelectOption[] | null => {
    return slackChannels
        ? slackChannels.map((x) => {
              const name = x.is_private_without_access ? 'Private Channel' : x.name
              const displayLabel = `${x.is_private ? '🔒' : '#'}${name} (${x.id})`
              return {
                  key: `${x.id}|#${x.name}`,
                  labelComponent: (
                      <span className="flex items-center">
                          <span>{displayLabel}</span>
                          <span>{x.is_ext_shared ? <IconSlackExternal className="ml-2" /> : null}</span>
                      </span>
                  ),
                  label: displayLabel,
              }
          })
        : null
}

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
        getChannelRefreshButtonDisabledReason,
    } = useValues(slackIntegrationLogic({ id: integration.id }))
    const { loadAllSlackChannels, loadSlackChannelById } = useActions(slackIntegrationLogic({ id: integration.id }))
    const [localValue, setLocalValue] = useState<string | null>(null)

    usePeriodicRerender(15000) // Re-render every 15 seconds for up-to-date `getChannelRefreshButtonDisabledReason`

    // If slackChannels aren't loaded, make sure we display only the channel name and not the actual underlying value
    const rawSlackChannelOptions = useMemo(() => getSlackChannelOptions(slackChannels), [slackChannels])

    const slackChannelOptions = (): LemonInputSelectOption[] | null => {
        return rawSlackChannelOptions
            ? rawSlackChannelOptions.filter((x) => {
                  const [id] = x.key.split('|#')
                  // Only show a private channel if searching for the exact channelId or it's currently selected
                  return !isPrivateChannelWithoutAccess(id) || id === value || id === localValue
              })
            : []
    }
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
                        setLocalValue(val)
                    }
                }}
                value={modifiedValue ? [modifiedValue] : []}
                onFocus={() => !slackChannels.length && !allSlackChannelsLoading && loadAllSlackChannels()}
                disabled={disabled}
                mode="single"
                data-attr="select-slack-channel"
                placeholder="Select a channel..."
                action={{
                    children: <span className="Link">Refresh channels</span>,
                    onClick: () => loadAllSlackChannels(true),
                    disabledReason: getChannelRefreshButtonDisabledReason(),
                }}
                emptyStateComponent={
                    <p className="text-secondary italic p-1">
                        No channels found. Make sure the PostHog Slack App is installed in the channel.{' '}
                        <Link to="https://posthog.com/docs/cdp/destinations/slack" target="_blank">
                            See the docs for more information.
                        </Link>
                    </p>
                }
                options={
                    slackChannelOptions() ??
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
                        <LemonButton
                            type="secondary"
                            disabledReason={getChannelRefreshButtonDisabledReason()}
                            onClick={() => loadAllSlackChannels(true)}
                            loading={allSlackChannelsLoading}
                        >
                            Check again
                        </LemonButton>
                    </div>
                </LemonBanner>
            ) : isPrivateChannelWithoutAccess(value ?? '') ? (
                <LemonBanner type="info">
                    This is a private Slack channel. Ask{' '}
                    <ProfilePicture user={integration.created_by} showName size="sm" /> or connect your own Slack
                    account to configure private channels.
                </LemonBanner>
            ) : null}
        </>
    )
}
