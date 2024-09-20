import { LemonBanner, LemonButton, LemonInputSelect, LemonInputSelectOption, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconSlackExternal } from 'lib/lemon-ui/icons'
import { useMemo } from 'react'

import { IntegrationType, SlackChannelType } from '~/types'

import { slackIntegrationLogic } from './slackIntegrationLogic'

const getSlackChannelOptions = (slackChannels?: SlackChannelType[] | null): LemonInputSelectOption[] | null => {
    return slackChannels
        ? slackChannels.map((x) => ({
              key: `${x.id}|#${x.name}`,
              labelComponent: (
                  <span className="flex items-center">
                      {x.is_private ? `🔒${x.name}` : `#${x.name}`}
                      {x.is_ext_shared ? <IconSlackExternal className="ml-2" /> : null}
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
    const { slackChannels, slackChannelsLoading, isMemberOfSlackChannel } = useValues(
        slackIntegrationLogic({ id: integration.id })
    )
    const { loadSlackChannels } = useActions(slackIntegrationLogic({ id: integration.id }))

    // If slackChannels aren't loaded, make sure we display only the channel name and not the actual underlying value
    const slackChannelOptions = useMemo(() => getSlackChannelOptions(slackChannels), [slackChannels])
    const showSlackMembershipWarning = value && isMemberOfSlackChannel(value) === false

    // Sometimes the parent will only store the channel ID and not the name, so we need to handle that

    const modifiedValue = useMemo(() => {
        if (value?.split('|').length === 1) {
            const channel = slackChannels?.find((x) => x.id === value)

            if (channel) {
                return `${channel.id}|#${channel.name}`
            }
        }

        return value
    }, [value, slackChannels])

    return (
        <>
            <LemonInputSelect
                onChange={(val) => onChange?.(val[0] ?? null)}
                value={modifiedValue ? [modifiedValue] : []}
                onFocus={() => !slackChannels && !slackChannelsLoading && loadSlackChannels()}
                disabled={disabled}
                mode="single"
                data-attr="select-slack-channel"
                placeholder="Select a channel..."
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
                loading={slackChannelsLoading}
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
                        <LemonButton type="secondary" onClick={loadSlackChannels} loading={slackChannelsLoading}>
                            Check again
                        </LemonButton>
                    </div>
                </LemonBanner>
            ) : null}
        </>
    )
}
