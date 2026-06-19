import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef, useState } from 'react'

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

import { IntegrationType, SlackChannelType } from '~/types'

import { slackChannelId } from './slackChannel'
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

// Slack channel IDs are 9+ char uppercase alphanumerics beginning with C (public), G (private), or D (DM).
// Only trigger a direct lookup against Slack when the typed text plausibly *is* a channel ID, so
// free-text channel names route through the search endpoint instead.
const SLACK_CHANNEL_ID_PATTERN = /^[CGD][A-Z0-9]{8,}$/

const getSlackChannelOptions = (slackChannels?: SlackChannelType[] | null): LemonInputSelectOption[] | null => {
    return slackChannels
        ? slackChannels.map((x) => {
              // Channel names are unique per workspace, so the friendly name alone identifies a channel.
              // Inaccessible private channels have no readable name, so there we keep the id to disambiguate.
              const displayLabel = x.is_private_without_access
                  ? `🔒Private channel (${x.id})`
                  : `${x.is_private ? '🔒' : '#'}${x.name}`
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
        slackChannelsForPicker,
        allSlackChannels,
        allSlackChannelsLoading,
        slackChannelByIdLoading,
        isMemberOfSlackChannel,
        isPrivateChannelWithoutAccess,
        getChannelRefreshButtonDisabledReason,
    } = useValues(slackIntegrationLogic({ id: integration.id }))
    const { loadAllSlackChannels, loadSlackChannelById, loadSlackChannelByIdSuccess } = useActions(
        slackIntegrationLogic({ id: integration.id })
    )
    const [localValue, setLocalValue] = useState<string | null>(null)
    // Gates the empty-val recovery reload: LemonInputSelect's setInputValue('') on blur and
    // after-select would otherwise flicker the "first page of channels" hint on every focus cycle.
    const hasActiveSearchRef = useRef(false)

    const channelRefreshButtonDisabledReason = getChannelRefreshButtonDisabledReason()
    // 1s tick while the cooldown is active so the countdown updates; otherwise idle the rerender (60s, picker is short-lived).
    usePeriodicRerender(channelRefreshButtonDisabledReason ? 1000 : 60_000)

    // If slackChannels aren't loaded, make sure we display only the channel name and not the actual underlying value
    const rawSlackChannelOptions = useMemo(
        () => getSlackChannelOptions(slackChannelsForPicker),
        [slackChannelsForPicker]
    )

    const slackChannelOptions = (): LemonInputSelectOption[] | null => {
        return rawSlackChannelOptions
            ? rawSlackChannelOptions.filter((x) => {
                  const id = slackChannelId(x.key)
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

    // Workspaces with hundreds of channels can have the saved channel beyond the first page that
    // /channels returns. Without a direct lookup the channel never makes it into slackChannels, so
    // LemonInputSelect can't find an option matching the saved value's key and falls back to
    // displaying the raw value text — e.g. "C0881TYHT41|#sentry-alerts" instead of the friendly
    // "#sentry-alerts". Fire the by-id fetch for both bare and composite values so
    // the channel is merged into slackChannels regardless of bulk-list position; the label only
    // renders correctly when the option exists in the picker's options list.
    useEffect(() => {
        if (!disabled && value) {
            const channelId = value.split('|')[0]
            if (channelId) {
                loadSlackChannelById(channelId)
            }
        }
    }, [loadSlackChannelById, value, disabled])

    return (
        <>
            <LemonInputSelect
                onChange={(val) => {
                    const key = val[0] ?? null
                    if (key) {
                        // Pin into the by-id slot so the post-select bulk reload can't drop the
                        // channel from slackChannels and unresolve the label.
                        const [channelId] = key.split('|')
                        const channel = slackChannels.find((c: SlackChannelType) => c.id === channelId)
                        if (channel) {
                            loadSlackChannelByIdSuccess(channel)
                        }
                    }
                    onChange?.(key)
                }}
                onInputChange={(val) => {
                    if (val) {
                        // Slack channel IDs are uppercase; normalize so pasted lowercase IDs still
                        // resolve via direct lookup. ID-shape input fires only the direct lookup;
                        // anything else fires only the search, skipping the otherwise-redundant
                        // by-id call for a free-text channel name.
                        const idCandidate = val.trim().toUpperCase()
                        if (SLACK_CHANNEL_ID_PATTERN.test(idCandidate)) {
                            loadSlackChannelById(idCandidate)
                        } else if (val !== modifiedValue) {
                            // LemonInputSelect auto-fills the input with the selected option's key on
                            // focus (see LemonInputSelect._onFocus). Don't treat that auto-fill as a
                            // search — the composite "id|#name" matches no channel server-side and
                            // would overwrite the cached list with [], so the bare ID could no longer
                            // resolve to a name after blur.
                            loadAllSlackChannels(false, val)
                            hasActiveSearchRef.current = true
                        }
                        setLocalValue(val)
                    } else if (hasActiveSearchRef.current) {
                        loadAllSlackChannels()
                        hasActiveSearchRef.current = false
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
                    // The popover is portaled outside the modal and matchWidth only sets min-width,
                    // not max-width — without a cap the popover can grow to fit a long single line
                    // and spill past the modal edge.
                    <p className="text-secondary italic p-1 max-w-sm">
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

            {allSlackChannels?.has_more && !allSlackChannelsLoading ? (
                <p className="text-secondary text-xs mt-1 mb-0">
                    Only the first page of channels is shown — type to search for a specific channel.
                </p>
            ) : null}

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
