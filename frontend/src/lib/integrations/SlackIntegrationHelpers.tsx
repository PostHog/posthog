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

import api from 'lib/api'
import { usePeriodicRerender } from 'lib/hooks/usePeriodicRerender'
import { IconSlackExternal } from 'lib/lemon-ui/icons'

import { IntegrationType, SlackChannelType, SlackUserType } from '~/types'

import { slackIntegrationLogic } from './slackIntegrationLogic'

export function SlackNotConfiguredBanner(): JSX.Element {
    return (
        <LemonBanner type="info">
            <div className="flex justify-between gap-2 items-center">
                <span>
                    Slack is not yet configured for this project. Add PostHog to your Slack workspace to continue.
                </span>
                <Link
                    to={api.integrations.authorizeUrl({
                        kind: 'slack',
                        next: window.location.pathname + '?target_type=slack',
                    })}
                    disableClientSideRouting
                >
                    <img
                        alt="Add to Slack"
                        height="40"
                        width="139"
                        src="https://platform.slack-edge.com/img/add_to_slack.png"
                        srcSet="https://platform.slack-edge.com/img/add_to_slack.png 1x, https://platform.slack-edge.com/img/add_to_slack@2x.png 2x"
                    />
                </Link>
            </div>
        </LemonBanner>
    )
}

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

const getSlackUserOptions = (slackUsers?: SlackUserType[] | null): LemonInputSelectOption[] => {
    // Match the channel key format so consumers (subscriptions, alerts) see a uniform
    // `<id>|<display>` shape regardless of whether the target is a channel or a DM.
    return slackUsers
        ? slackUsers.map((u) => {
              const displayLabel = `@${u.name} (${u.id})`
              return {
                  key: `${u.id}|@${u.name}`,
                  label: displayLabel,
              }
          })
        : []
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
        slackUsers,
        allSlackUsersLoading,
        isMemberOfSlackChannel,
        isPrivateChannelWithoutAccess,
        getChannelRefreshButtonDisabledReason,
    } = useValues(slackIntegrationLogic({ id: integration.id }))
    const { loadAllSlackChannels, loadSlackChannelById, loadAllSlackUsers } = useActions(
        slackIntegrationLogic({ id: integration.id })
    )

    // Only load (and offer) people if the install has been authorized with the DM scopes.
    // Older installs grant only channel scopes; surfacing people in the picker would
    // create a "looks pickable, fails on save" trap. The serializer's create-time 400
    // (code=slack_dm_needs_reauth) is the backstop for any caller that tries anyway.
    const supportsDms = (integration.config?.scope ?? '').split(',').includes('im:write')
    const [localValue, setLocalValue] = useState<string | null>(null)

    const channelRefreshButtonDisabledReason = getChannelRefreshButtonDisabledReason()
    // 1s tick while the cooldown is active so the countdown updates; otherwise idle the rerender (60s, picker is short-lived).
    usePeriodicRerender(channelRefreshButtonDisabledReason ? 1000 : 60_000)

    // If slackChannels aren't loaded, make sure we display only the channel name and not the actual underlying value
    const rawSlackChannelOptions = useMemo(() => getSlackChannelOptions(slackChannels), [slackChannels])
    const rawSlackUserOptions = useMemo(() => getSlackUserOptions(slackUsers), [slackUsers])

    const slackChannelOptions = (): LemonInputSelectOption[] | null => {
        const channels = rawSlackChannelOptions
            ? rawSlackChannelOptions.filter((x) => {
                  const [id] = x.key.split('|#')
                  // Only show a private channel if searching for the exact channelId or it's currently selected
                  return !isPrivateChannelWithoutAccess(id) || id === value || id === localValue
              })
            : []
        // Append users below channels when the install supports DMs. Sorting per-section
        // keeps channel grouping intact while letting the People list stay alphabetical.
        return supportsDms ? [...channels, ...rawSlackUserOptions] : channels
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
            if (supportsDms) {
                loadAllSlackUsers()
            }
        }
    }, [loadAllSlackChannels, loadAllSlackUsers, disabled, supportsDms])

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
                    disabledReason: channelRefreshButtonDisabledReason,
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
                loading={allSlackChannelsLoading || slackChannelByIdLoading || allSlackUsersLoading}
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
