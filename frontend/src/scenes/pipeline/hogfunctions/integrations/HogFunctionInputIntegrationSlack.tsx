import { LemonButton, LemonMenu, LemonSkeleton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { IconSlack } from 'lib/lemon-ui/icons'
import { integrationsLogic } from 'scenes/settings/project/integrationsLogic'

import { HogFunctionInputIntegrationConfigureProps } from './types'

export function HogFunctionIntegrationSlackConnection({
    onChange,
    value,
}: HogFunctionInputIntegrationConfigureProps): JSX.Element {
    const { integrationsLoading, slackIntegrations, addToSlackButtonUrl } = useValues(integrationsLogic)

    const integration = slackIntegrations?.find((integration) => `${integration.id}` === value)

    if (integrationsLoading) {
        return <LemonSkeleton className="h-10" />
    }

    const button = (
        <LemonMenu
            items={[
                ...(slackIntegrations?.map((integration) => ({
                    icon: <IconSlack />,
                    onClick: () => onChange?.(`${integration.id}`),
                    label: integration.config.team.name,
                })) || []),
                {
                    to: addToSlackButtonUrl(window.location.pathname + '?target_type=slack') || '',
                    label: 'Add to different Slack workspace',
                },
            ]}
        >
            {integration ? (
                <LemonButton type="secondary">Change</LemonButton>
            ) : (
                <LemonButton type="secondary"> Choose Slack connection</LemonButton>
            )}
        </LemonMenu>
    )

    return (
        <>
            {integration ? (
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

                    {button}
                </div>
            ) : (
                button
            )}
        </>
    )
}

// export function HogFunctionIntegrationSlack(): JSX.Element {
//     const { slackChannels, slackChannelsLoading, slackIntegration, addToSlackButtonUrl } = useValues(integrationsLogic)
//     const { loadSlackChannels } = useActions(integrationsLogic)

//     const slackDisabled = !slackIntegration

//     // If slackChannels aren't loaded, make sure we display only the channel name and not the actual underlying value
//     const slackChannelOptions: LemonInputSelectOption[] = useMemo(
//         () => getSlackChannelOptions(subscription?.target_value, slackChannels),
//         [slackChannels, subscription?.target_value]
//     )

//     const showSlackMembershipWarning =
//         subscription.target_value &&
//         subscription.target_type === 'slack' &&
//         !isMemberOfSlackChannel(subscription.target_value)

//     return (
//         <>
//             <>
//                 <LemonField
//                     name="target_value"
//                     label="Which Slack channel to send reports to"
//                     help={
//                         <>
//                             Private channels are only shown if you have{' '}
//                             <Link to="https://posthog.com/docs/webhooks/slack" target="_blank">
//                                 added the PostHog Slack App
//                             </Link>{' '}
//                             to them
//                         </>
//                     }
//                 >
//                     {({ value, onChange }) => (
//                         <LemonInputSelect
//                             onChange={(val) => onChange(val[0] ?? null)}
//                             value={value ? [value] : []}
//                             disabled={slackDisabled}
//                             mode="single"
//                             data-attr="select-slack-channel"
//                             placeholder="Select a channel..."
//                             options={slackChannelOptions}
//                             loading={slackChannelsLoading}
//                         />
//                     )}
//                 </LemonField>

//                 {showSlackMembershipWarning ? (
//                     <LemonField name="memberOfSlackChannel">
//                         <LemonBanner type="info">
//                             <div className="flex gap-2 items-center">
//                                 <span>
//                                     The PostHog Slack App is not in this channel. Please add it to the channel otherwise
//                                     Subscriptions will fail to be delivered.{' '}
//                                     <Link to="https://posthog.com/docs/webhooks/slack" target="_blank">
//                                         See the Docs for more information
//                                     </Link>
//                                 </span>
//                                 <LemonButton
//                                     type="secondary"
//                                     onClick={loadSlackChannels}
//                                     loading={slackChannelsLoading}
//                                 >
//                                     Check again
//                                 </LemonButton>
//                             </div>
//                         </LemonBanner>
//                     </LemonField>
//                 ) : null}
//             </>
//         </>
//     )
// }
