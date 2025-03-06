import { LemonBanner, LemonButton, LemonInputSelect, LemonInputSelectOption, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconSlackExternal } from 'lib/lemon-ui/icons'
import { useEffect, useMemo } from 'react'

import { IntegrationType, SlackChannelType } from '~/types'

import { slackIntegrationLogic } from './slackIntegrationLogic'

const getSlackChannelOptions = (slackChannels?: SlackChannelType[] | null): LemonInputSelectOption[] | null => {
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
}

export type SlackChannelPickerProps = {
    integration: IntegrationType
    value?: string
    onChange?: (value: string | null) => void
    disabled?: boolean
}

export function SlackChannelPicker({ onChange, value, integration, disabled }: SlackChannelPickerProps): JSX.Element {
    const { slackChannels, allSlackChannelsLoading, slackChannelByIdLoading, isMemberOfSlackChannel } = useValues(
        slackIntegrationLogic({ id: integration.id })
    )
    const { loadAllSlackChannels, loadSlackChannelById } = useActions(slackIntegrationLogic({ id: integration.id }))

    // If slackChannels aren't loaded, make sure we display only the channel name and not the actual underlying value
    const slackChannelOptions = useMemo(() => getSlackChannelOptions(slackChannels.list()), [slackChannels])
    const showSlackMembershipWarning = value && isMemberOfSlackChannel(value) === false

    // Sometimes the parent will only store the channel ID and not the name, so we need to handle that

    const modifiedValue = useMemo(() => {
        if (value?.split('|').length === 1) {
            const channel = slackChannels.list().find((x: SlackChannelType) => x.id === value)

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
                    }
                }}
                value={modifiedValue ? [modifiedValue] : []}
                onFocus={() => !slackChannels.list().length && !allSlackChannelsLoading && loadAllSlackChannels()}
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
            ) : null}
        </>
    )
}
