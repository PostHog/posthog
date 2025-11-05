import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconChevronLeft } from '@posthog/icons'
import { LemonInput, LemonTextArea, Link } from '@posthog/lemon-ui'

import api from 'lib/api'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { usersLemonSelectOptions } from 'lib/components/UserSelectItem'
import { dayjs } from 'lib/dayjs'
import { SlackChannelPicker } from 'lib/integrations/SlackIntegrationHelpers'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { membersLogic } from 'scenes/organization/membersLogic'

import { subscriptionLogic } from '../subscriptionLogic'
import { subscriptionsLogic } from '../subscriptionsLogic'
import {
    SubscriptionBaseProps,
    bysetposOptions,
    frequencyOptionsPlural,
    frequencyOptionsSingular,
    intervalOptions,
    monthlyWeekdayOptions,
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

    const { meFirstMembers, membersLoading } = useValues(membersLogic)
    const { subscription, subscriptionLoading, isSubscriptionSubmitting, subscriptionChanged } = useValues(logic)
    const { preflight, siteUrlMisconfigured } = useValues(preflightLogic)
    const { deleteSubscription } = useActions(subscriptionslogic)
    const { slackIntegrations } = useValues(integrationsLogic)
    // TODO: Fix this so that we use the appropriate config...
    const firstSlackIntegration = slackIntegrations?.[0]

    const emailDisabled = !preflight?.email_service_available

    const _onDelete = (): void => {
        if (id !== 'new') {
            deleteSubscription(id)
            onDelete()
        }
    }

    const formatter = new Intl.DateTimeFormat('en-US', { timeZoneName: 'shortGeneric' })
    const parts = formatter.formatToParts(new Date())
    const currentTimezone = parts?.find((part) => part.type === 'timeZoneName')?.value

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

            <LemonModal.Content className="deprecated-space-y-2">
                {!subscription ? (
                    subscriptionLoading ? (
                        <div className="deprecated-space-y-4">
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
                                        <LemonInputSelect
                                            onChange={(val) => onChange(val.join(','))}
                                            value={value?.split(',').filter(Boolean)}
                                            disabled={emailDisabled}
                                            mode="multiple"
                                            allowCustomValues
                                            data-attr="subscribed-emails"
                                            options={usersLemonSelectOptions(meFirstMembers.map((x) => x.user))}
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
                                {!firstSlackIntegration ? (
                                    <>
                                        <LemonBanner type="info">
                                            <div className="flex justify-between gap-2">
                                                <span>
                                                    Slack is not yet configured for this project. Add PostHog to your
                                                    Slack workspace to continue.
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
                                    </>
                                ) : (
                                    <>
                                        <LemonField
                                            name="target_value"
                                            label="Which Slack channel to send reports to"
                                            help={
                                                <>
                                                    Private channels are only shown if you have{' '}
                                                    <Link to="https://posthog.com/docs/webhooks/slack" target="_blank">
                                                        added the PostHog Slack App
                                                    </Link>{' '}
                                                    to them. You can also paste the channel ID (e.g.{' '}
                                                    <code>C1234567890</code>) to search for channels.
                                                </>
                                            }
                                        >
                                            {({ value, onChange }) => (
                                                <SlackChannelPicker
                                                    value={value}
                                                    onChange={onChange}
                                                    integration={firstSlackIntegration}
                                                />
                                            )}
                                        </LemonField>
                                    </>
                                )}
                            </>
                        ) : null}

                        {subscription.target_type === 'webhook' ? (
                            <>
                                <LemonField name="target_value" label="Webhook URL">
                                    <LemonInput placeholder="https://example.com/webhooks/1234" />
                                </LemonField>
                                <div className="text-xs text-secondary mt-2">
                                    Webhooks will be called with a HTTP POST request. The webhook endpoint should
                                    respond with a healthy HTTP code (2xx).
                                </div>
                            </>
                        ) : null}

                        <div>
                            <div className="flex items-baseline justify-between w-full">
                                <LemonLabel className="mb-2">Recurrence</LemonLabel>
                                <div className="text-xs text-secondary text-right">{currentTimezone}</div>
                            </div>
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
