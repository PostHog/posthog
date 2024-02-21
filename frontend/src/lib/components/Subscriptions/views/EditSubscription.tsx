import { LemonInput, LemonTextArea, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { usersLemonSelectOptions } from 'lib/components/UserSelectItem'
import { dayjs } from 'lib/dayjs'
import { IconChevronLeft } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import {
    LemonSelectMultiple,
    LemonSelectMultipleOptionItem,
} from 'lib/lemon-ui/LemonSelectMultiple/LemonSelectMultiple'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { useEffect, useMemo } from 'react'
import { membersLogic } from 'scenes/organization/membersLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { integrationsLogic } from 'scenes/settings/project/integrationsLogic'
import { urls } from 'scenes/urls'

import { subscriptionLogic } from '../subscriptionLogic'
import { subscriptionsLogic } from '../subscriptionsLogic'
import {
    bysetposOptions,
    frequencyOptionsPlural,
    frequencyOptionsSingular,
    getSlackChannelOptions,
    intervalOptions,
    monthlyWeekdayOptions,
    SubscriptionBaseProps,
    targetTypeOptions,
    timeOptions,
    weekdayOptions,
} from '../utils'

interface EditSubscriptionProps extends SubscriptionBaseProps {
    id: number | 'new'
    onCancel: () => void
    onDelete: () => void
}

export function EditSubscription({
    id,
    insightShortId,
    dashboardId,
    onCancel,
    onDelete,
}: EditSubscriptionProps): JSX.Element {
    const logicProps = {
        id,
        insightShortId,
        dashboardId,
    }
    const logic = subscriptionLogic(logicProps)
    const subscriptionslogic = subscriptionsLogic({
        insightShortId,
        dashboardId,
    })

    const { members, membersLoading } = useValues(membersLogic)
    const { subscription, subscriptionLoading, isSubscriptionSubmitting, subscriptionChanged, isMemberOfSlackChannel } =
        useValues(logic)
    const { preflight, siteUrlMisconfigured } = useValues(preflightLogic)
    const { deleteSubscription } = useActions(subscriptionslogic)
    const { slackChannels, slackChannelsLoading, slackIntegration, addToSlackButtonUrl } = useValues(integrationsLogic)
    const { loadSlackChannels } = useActions(integrationsLogic)

    const emailDisabled = !preflight?.email_service_available
    const slackDisabled = !slackIntegration

    const _onDelete = (): void => {
        if (id !== 'new') {
            deleteSubscription(id)
            onDelete()
        }
    }

    useEffect(() => {
        if (subscription?.target_type === 'slack' && slackIntegration) {
            loadSlackChannels()
        }
    }, [subscription?.target_type, slackIntegration])

    // If slackChannels aren't loaded, make sure we display only the channel name and not the actual underlying value
    const slackChannelOptions: LemonSelectMultipleOptionItem[] = useMemo(
        () => getSlackChannelOptions(subscription?.target_value, slackChannels),
        [slackChannels, subscription?.target_value]
    )

    const showSlackMembershipWarning =
        subscription.target_value &&
        subscription.target_type === 'slack' &&
        !isMemberOfSlackChannel(subscription.target_value)

    return (
        <Form
            logic={subscriptionLogic}
            props={logicProps}
            formKey="subscription"
            enableFormOnSubmit
            className="LemonModal__layout"
        >
            <LemonModal.Header>
                <div className="flex items-center gap-2">
                    <LemonButton icon={<IconChevronLeft />} onClick={onCancel} size="xsmall" />

                    <h3>{id === 'new' ? 'New' : 'Edit '} Subscription</h3>
                </div>
            </LemonModal.Header>

            <LemonModal.Content className="space-y-2">
                {!subscription ? (
                    subscriptionLoading ? (
                        <div className="space-y-4">
                            <LemonSkeleton className="w-1/2 h-4" />
                            <LemonSkeleton.Row />
                            <LemonSkeleton className="w-1/2 h-4" />
                            <LemonSkeleton.Row />
                            <LemonSkeleton className="w-1/2 h-4" />
                            <LemonSkeleton.Row />
                        </div>
                    ) : (
                        <div className="p-4 text-center">
                            <h2>Not found</h2>
                            <p>This subscription could not be found. It may have been deleted.</p>
                        </div>
                    )
                ) : (
                    <>
                        {subscription?.created_by ? (
                            <UserActivityIndicator
                                at={subscription.created_at}
                                by={subscription.created_by}
                                prefix="Created"
                                className="mb-4"
                            />
                        ) : null}

                        {siteUrlMisconfigured && (
                            <LemonBanner type="warning">
                                <>
                                    Your <code>SITE_URL</code> environment variable seems misconfigured. Your{' '}
                                    <code>SITE_URL</code> is set to{' '}
                                    <b>
                                        <code>{preflight?.site_url}</code>
                                    </b>{' '}
                                    but you're currently browsing this page from{' '}
                                    <b>
                                        <code>{window.location.origin}</code>
                                    </b>
                                    . <br />
                                    If this value is not configured correctly PostHog may be unable to correctly send
                                    Subscriptions.{' '}
                                    <Link
                                        to="https://posthog.com/docs/configuring-posthog/environment-variables?utm_medium=in-product&utm_campaign=subcriptions-system-status-site-url-misconfig"
                                        target="_blank"
                                        targetBlankIcon
                                    >
                                        Learn more
                                    </Link>
                                </>
                            </LemonBanner>
                        )}

                        <LemonField name="title" label="Name">
                            <LemonInput placeholder="e.g. Weekly team report" />
                        </LemonField>

                        <LemonField name="target_type" label="Destination">
                            <LemonSelect options={targetTypeOptions} />
                        </LemonField>

                        {subscription.target_type === 'email' ? (
                            <>
                                {emailDisabled && (
                                    <LemonBanner type="error">
                                        <>
                                            Email subscriptions are not currently possible as this PostHog instance
                                            isn't{' '}
                                            <Link
                                                to="https://posthog.com/docs/self-host/configure/email"
                                                target="_blank"
                                                targetBlankIcon
                                            >
                                                configured&nbsp;to&nbsp;send&nbsp;emails&nbsp;
                                            </Link>
                                            .
                                        </>
                                    </LemonBanner>
                                )}

                                <LemonField
                                    name="target_value"
                                    label="Who do you want to subscribe"
                                    help="Enter the email addresses of the users you want to share with"
                                >
                                    {({ value, onChange }) => (
                                        <LemonSelectMultiple
                                            onChange={(val: string[]) => onChange(val.join(','))}
                                            value={value?.split(',').filter(Boolean)}
                                            disabled={emailDisabled}
                                            mode="multiple-custom"
                                            data-attr="subscribed-emails"
                                            options={usersLemonSelectOptions(members.map((x) => x.user))}
                                            loading={membersLoading}
                                            placeholder="Enter an email address"
                                        />
                                    )}
                                </LemonField>

                                <LemonField name="invite_message" label="Message" showOptional>
                                    <LemonTextArea placeholder="Your message to new subscribers (optional)" />
                                </LemonField>
                            </>
                        ) : null}

                        {subscription.target_type === 'slack' ? (
                            <>
                                {slackDisabled ? (
                                    <>
                                        {addToSlackButtonUrl() ? (
                                            <LemonBanner type="info">
                                                <div className="flex justify-between gap-2">
                                                    <span>
                                                        Slack is not yet configured for this project. Add PostHog to
                                                        your Slack workspace to continue.
                                                    </span>
                                                    <Link
                                                        to={
                                                            addToSlackButtonUrl(
                                                                window.location.pathname + '?target_type=slack'
                                                            ) || ''
                                                        }
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
                                        ) : (
                                            <LemonBanner type="error">
                                                <>
                                                    Slack is not yet configured for this project. You can configure it
                                                    at{' '}
                                                    <Link to={`${urls.settings('project')}#slack`}>
                                                        {' '}
                                                        Slack Integration settings
                                                    </Link>
                                                    .
                                                </>
                                            </LemonBanner>
                                        )}
                                    </>
                                ) : (
                                    <>
                                        <LemonField
                                            name="target_value"
                                            label="Which Slack channel to send reports to"
                                            help={
                                                <>
                                                    Private channels are only shown if you have{' '}
                                                    <Link
                                                        to="https://posthog.com/docs/integrate/third-party/slack"
                                                        target="_blank"
                                                    >
                                                        added the PostHog Slack App
                                                    </Link>{' '}
                                                    to them
                                                </>
                                            }
                                        >
                                            {({ value, onChange }) => (
                                                <LemonSelectMultiple
                                                    onChange={(val: string) => onChange(val)}
                                                    value={value}
                                                    disabled={slackDisabled}
                                                    mode="single"
                                                    data-attr="select-slack-channel"
                                                    options={slackChannelOptions}
                                                    loading={slackChannelsLoading}
                                                />
                                            )}
                                        </LemonField>

                                        {showSlackMembershipWarning ? (
                                            <LemonField name="memberOfSlackChannel">
                                                <LemonBanner type="info">
                                                    <div className="flex gap-2 items-center">
                                                        <span>
                                                            The PostHog Slack App is not in this channel. Please add it
                                                            to the channel otherwise Subscriptions will fail to be
                                                            delivered.{' '}
                                                            <Link
                                                                to="https://posthog.com/docs/integrate/third-party/slack"
                                                                target="_blank"
                                                            >
                                                                See the Docs for more information
                                                            </Link>
                                                        </span>
                                                        <LemonButton
                                                            type="secondary"
                                                            onClick={loadSlackChannels}
                                                            loading={slackChannelsLoading}
                                                        >
                                                            Check again
                                                        </LemonButton>
                                                    </div>
                                                </LemonBanner>
                                            </LemonField>
                                        ) : null}
                                    </>
                                )}
                            </>
                        ) : null}

                        {subscription.target_type === 'webhook' ? (
                            <>
                                <LemonField name="target_value" label="Webhook URL">
                                    <LemonInput placeholder="https://example.com/webhooks/1234" />
                                </LemonField>
                                <div className="text-xs text-muted mt-2">
                                    Webhooks will be called with a HTTP POST request. The webhook endpoint should
                                    respond with a healthy HTTP code (2xx).
                                </div>
                            </>
                        ) : null}

                        <div>
                            <LemonLabel className="mb-2">Recurrence</LemonLabel>
                            <div className="flex gap-2 items-center rounded border p-2 flex-wrap">
                                <span>Send every</span>
                                <LemonField name="interval">
                                    <LemonSelect options={intervalOptions} />
                                </LemonField>
                                <LemonField name="frequency">
                                    <LemonSelect
                                        options={
                                            subscription.interval === 1
                                                ? frequencyOptionsSingular
                                                : frequencyOptionsPlural
                                        }
                                    />
                                </LemonField>

                                {subscription.frequency === 'weekly' && (
                                    <>
                                        <span>on</span>
                                        <LemonField name="byweekday">
                                            {({ value, onChange }) => (
                                                <LemonSelect
                                                    options={weekdayOptions}
                                                    value={value ? value[0] : null}
                                                    onChange={(val) => onChange([val])}
                                                />
                                            )}
                                        </LemonField>
                                    </>
                                )}

                                {subscription.frequency === 'monthly' && (
                                    <>
                                        <span>on the</span>
                                        <LemonField name="bysetpos">
                                            {({ value, onChange }) => (
                                                <LemonSelect
                                                    options={bysetposOptions}
                                                    value={value ? String(value) : null}
                                                    onChange={(val) => {
                                                        onChange(typeof val === 'string' ? parseInt(val, 10) : null)
                                                    }}
                                                />
                                            )}
                                        </LemonField>
                                        <LemonField name="byweekday">
                                            {({ value, onChange }) => (
                                                <LemonSelect
                                                    dropdownMatchSelectWidth={false}
                                                    options={monthlyWeekdayOptions}
                                                    // "day" is a special case where it is a list of all available days
                                                    value={value ? (value.length === 1 ? value[0] : 'day') : null}
                                                    onChange={(val) =>
                                                        onChange(
                                                            val === 'day'
                                                                ? Object.values(weekdayOptions).map((v) => v.value)
                                                                : [val]
                                                        )
                                                    }
                                                />
                                            )}
                                        </LemonField>
                                    </>
                                )}
                                <span>by</span>
                                <LemonField name="start_date">
                                    {({ value, onChange }) => (
                                        <LemonSelect
                                            options={timeOptions}
                                            value={dayjs(value).hour().toString()}
                                            onChange={(val) => {
                                                onChange(
                                                    dayjs()
                                                        .hour(typeof val === 'string' ? parseInt(val, 10) : 0)
                                                        .minute(0)
                                                        .second(0)
                                                        .toISOString()
                                                )
                                            }}
                                        />
                                    )}
                                </LemonField>
                            </div>
                        </div>
                    </>
                )}
            </LemonModal.Content>

            <LemonModal.Footer>
                <div className="flex-1">
                    {subscription && id !== 'new' && (
                        <LemonButton
                            type="secondary"
                            status="danger"
                            onClick={_onDelete}
                            disabled={subscriptionLoading}
                        >
                            Delete subscription
                        </LemonButton>
                    )}
                </div>
                <LemonButton type="secondary" onClick={onCancel}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    htmlType="submit"
                    loading={isSubscriptionSubmitting}
                    disabled={!subscriptionChanged || subscriptionLoading}
                >
                    {id === 'new' ? 'Create subscription' : 'Save'}
                </LemonButton>
            </LemonModal.Footer>
        </Form>
    )
}
