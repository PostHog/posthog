import { LemonBanner, LemonButton, LemonInputSelect, LemonInputSelectOption, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { IconSlack, IconSlackExternal } from 'lib/lemon-ui/icons'
import { useMemo } from 'react'

import { IntegrationType, SlackChannelType } from '~/types'

import { slackIntegrationLogic } from './slackIntegrationLogic'

export const getSlackChannelOptions = (
    value?: string,
    slackChannels?: SlackChannelType[] | null
): LemonInputSelectOption[] => {
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
        : value
        ? [
              {
                  key: value,
                  label: value?.split('|')?.pop() || value,
              },
          ]
        : []
}

export type SlackChannelPickerProps = {
    integration: IntegrationType
    value?: string
    onChange?: (value: string) => void
    disabled?: boolean
}

export function SlackChannelPicker({ onChange, value, integration, disabled }: SlackChannelPickerProps): JSX.Element {
    const { slackChannels, slackChannelsLoading, isMemberOfSlackChannel } = useValues(
        slackIntegrationLogic({ id: integration.id })
    )
    const { loadSlackChannels } = useActions(slackIntegrationLogic({ id: integration.id }))

    // If slackChannels aren't loaded, make sure we display only the channel name and not the actual underlying value
    const slackChannelOptions = useMemo(() => getSlackChannelOptions(value, slackChannels), [slackChannels, value])
    const showSlackMembershipWarning = value && isMemberOfSlackChannel(value) === false

    return (
        <>
            <LemonInputSelect
                onChange={(val) => onChange?.(val[0] ?? null)}
                value={value ? [value] : []}
                onFocus={() => !slackChannels && !slackChannelsLoading && loadSlackChannels()}
                disabled={disabled}
                mode="single"
                data-attr="select-slack-channel"
                placeholder="Select a channel..."
                options={slackChannelOptions}
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

export function SlackIntegrationView({
    integration,
    suffix,
}: {
    integration: IntegrationType
    suffix?: JSX.Element
}): JSX.Element {
    return (
        <div className="rounded border flex justify-between items-center p-2 bg-bg-light">
            <div className="flex items-center gap-4 ml-2">
                <IconSlack className="text-2xl" />
                <div>
                    <div>
                        Connected to <strong>{integration.config.team.name}</strong> workspace
                    </div>
                    {integration.created_by ? (
                        <UserActivityIndicator
                            at={integration.created_at}
                            by={integration.created_by}
                            prefix="Updated"
                            className="text-muted"
                        />
                    ) : null}
                </div>
            </div>

            {suffix}
        </div>
    )
}
