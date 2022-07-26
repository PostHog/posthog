import React, { useEffect, useMemo } from 'react'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/components/LemonButton'
import { VerticalForm } from 'lib/forms/VerticalForm'
import { membersLogic } from 'scenes/organization/Settings/membersLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { Field } from 'lib/forms/Field'
import { dayjs } from 'lib/dayjs'
import { LemonSelect, LemonSelectOptions, LemonSelectProps } from 'lib/components/LemonSelect'
import { subscriptionLogic } from '../subscriptionLogic'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { IconChevronLeft, IconOpenInNew } from 'lib/components/icons'
import { AlertMessage } from 'lib/components/AlertMessage'
import { subscriptionsLogic } from '../subscriptionsLogic'
import {
    bysetposOptions,
    frequencyOptions,
    getSlackChannelOptions,
    intervalOptions,
    monthlyWeekdayOptions,
    SubscriptionBaseProps,
    targetTypeOptions,
    timeOptions,
    weekdayOptions,
} from '../utils'
import { LemonDivider, LemonInput, LemonTextArea, Link } from '@posthog/lemon-ui'
import {
    LemonSelectMultiple,
    LemonSelectMultipleOptionItem,
} from 'lib/components/LemonSelectMultiple/LemonSelectMultiple'
import { usersLemonSelectOptions } from 'lib/components/UserSelectItem'
import { integrationsLogic } from 'scenes/project/Settings/integrationsLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'
import { Skeleton } from 'antd'

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
    const { featureFlags } = useValues(featureFlagLogic)

    const emailDisabled = !preflight?.email_service_available
    const slackDisabled = !slackIntegration

    const _onDelete = (): void => {
        if (id !== 'new') {
            deleteSubscription(id)
            onDelete()
        }
    }

    const commonSelectProps: Partial<LemonSelectProps<LemonSelectOptions>> = {
        type: 'stealth',
        outlined: true,
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
        <>
            <VerticalForm logic={subscriptionLogic} props={logicProps} formKey="subscription" enableFormOnSubmit>
                <header className="flex items-center border-bottom pb-4">
                    <LemonButton type="stealth" onClick={onCancel} size="small">
                        <IconChevronLeft fontSize={'1rem'} />
                        Back
                    </LemonButton>
                    <LemonDivider vertical />

                    <h4 className="mt-2">{id === 'new' ? 'New' : 'Edit '} Subscription</h4>
                </header>

                {!subscription ? (
                    subscriptionLoading ? (
                        <>
                            <Skeleton />
                            <Skeleton />
                            <Skeleton />
                        </>
                    ) : (
                        <section className="p-4 text-center">
                            <h2>Not found</h2>
                            <p>This subscription could not be found. It may have been deleted.</p>
                        </section>
                    )
                ) : (
                    <section>
                        {subscription?.created_by ? (
                            <UserActivityIndicator
                                at={subscription.created_at}
                                by={subscription.created_by}
                                prefix={'Created'}
                                className={'mb'}
                            />
                        ) : null}

                        {siteUrlMisconfigured && (
                            <AlertMessage type="warning">
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
                                    <a
                                        target="_blank"
                                        rel="noopener"
                                        href="https://posthog.com/docs/configuring-posthog/environment-variables?utm_medium=in-product&utm_campaign=subcriptions-system-status-site-url-misconfig"
                                    >
                                        Learn more <IconOpenInNew />
                                    </a>
                                </>
                            </AlertMessage>
                        )}

                        <Field name={'title'} label={'Name'}>
                            <LemonInput placeholder="e.g. Weekly team report" />
                        </Field>

                        {featureFlags[FEATURE_FLAGS.SUBSCRIPTIONS_SLACK] && (
                            <Field name={'target_type'} label={'Destination'}>
                                <LemonSelect options={targetTypeOptions} {...commonSelectProps} />
                            </Field>
                        )}

                        {subscription.target_type === 'email' ? (
                            <>
                                {emailDisabled && (
                                    <AlertMessage type="error">
                                        <>
                                            Email subscriptions are not currently possible as this PostHog instance
                                            isn't{' '}
                                            <a
                                                href="https://posthog.com/docs/self-host/configure/email"
                                                target="_blank"
                                                rel="noopener"
                                            >
                                                configured&nbsp;to&nbsp;send&nbsp;emails&nbsp;
                                                <IconOpenInNew />
                                            </a>
                                            .
                                        </>
                                    </AlertMessage>
                                )}

                                <Field name={'target_value'} label={'Who do you want to subscribe'}>
                                    {({ value, onChange }) => (
                                        <>
                                            <LemonSelectMultiple
                                                onChange={(val) => onChange(val.join(','))}
                                                value={value?.split(',').filter(Boolean)}
                                                disabled={emailDisabled}
                                                mode="multiple-custom"
                                                data-attr="subscribed-emails"
                                                options={usersLemonSelectOptions(members.map((x) => x.user))}
                                                loading={membersLoading}
                                                placeholder="Enter an email address"
                                            />
                                            <div className="text-small text-muted mt-2">
                                                Enter the email addresses of the users you want to share with
                                            </div>
                                        </>
                                    )}
                                </Field>

                                <Field name={'invite_message'} label={'Message (optional)'}>
                                    <LemonTextArea placeholder="Your message to new subscribers (optional)" />
                                </Field>
                            </>
                        ) : null}

                        {subscription.target_type === 'slack' ? (
                            <>
                                {slackDisabled ? (
                                    <>
                                        {addToSlackButtonUrl() ? (
                                            <AlertMessage type="info">
                                                <div className="flex justify-between gap-2">
                                                    <span>
                                                        Slack is not yet configured for this project. Add PostHog to
                                                        your Slack workspace to continue.
                                                    </span>
                                                    <a
                                                        href={
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
                                                    </a>
                                                </div>
                                            </AlertMessage>
                                        ) : (
                                            <AlertMessage type="error">
                                                <>
                                                    Slack is not yet configured for this project. You can configure it
                                                    at{' '}
                                                    <Link to={`${urls.projectSettings()}#slack`}>
                                                        {' '}
                                                        Slack Integration settings
                                                    </Link>
                                                    .
                                                </>
                                            </AlertMessage>
                                        )}
                                    </>
                                ) : (
                                    <>
                                        <Field name={'target_value'} label={'Which Slack channel to send reports to'}>
                                            {({ value, onChange }) => (
                                                <>
                                                    <LemonSelectMultiple
                                                        onChange={(val) => onChange(val)}
                                                        value={value}
                                                        disabled={slackDisabled}
                                                        mode="single"
                                                        data-attr="select-slack-channel"
                                                        options={slackChannelOptions}
                                                        loading={slackChannelsLoading}
                                                    />
                                                    <div className="text-small text-muted mt-2">
                                                        Private channels are only shown if you have{' '}
                                                        <a
                                                            href="https://posthog.com/docs/integrate/third-party/slack"
                                                            target="_blank"
                                                            rel="noopener"
                                                        >
                                                            added the PostHog Slack App
                                                        </a>{' '}
                                                        to them
                                                    </div>
                                                </>
                                            )}
                                        </Field>

                                        {showSlackMembershipWarning ? (
                                            <Field name={'memberOfSlackChannel'}>
                                                <AlertMessage type="info">
                                                    <div className="flex gap-2 items-center">
                                                        <span>
                                                            The PostHog Slack App is not in this channel. Please add it
                                                            to the channel otherwise Subscriptions will fail to be
                                                            delivered.{' '}
                                                            <a
                                                                href="https://posthog.com/docs/integrate/third-party/slack"
                                                                target="_blank"
                                                                rel="noopener"
                                                            >
                                                                See the Docs for more information
                                                            </a>
                                                        </span>
                                                        <LemonButton
                                                            type="secondary"
                                                            onClick={() => loadSlackChannels()}
                                                            loading={slackChannelsLoading}
                                                        >
                                                            Check again
                                                        </LemonButton>
                                                    </div>
                                                </AlertMessage>
                                            </Field>
                                        ) : null}
                                    </>
                                )}
                            </>
                        ) : null}

                        {subscription.target_type === 'webhook' ? (
                            <>
                                <Field name={'target_value'} label={'Webhook URL'}>
                                    <LemonInput placeholder="https://example.com/webhooks/1234" />
                                </Field>
                                <div className="text-small text-muted mt-2">
                                    Webhooks will be called with a HTTP POST request. The webhook endpoint should
                                    respond with a healthy HTTP code (2xx).
                                </div>
                            </>
                        ) : null}

                        <div>
                            <div className="ant-form-item-label">
                                <label title="Recurrence">Recurrence</label>
                            </div>
                            <div className="flex gap-2 items-center rounded border-all pa-2 flex-wrap">
                                <span>Send every</span>
                                <Field name={'interval'} style={{ marginBottom: 0 }}>
                                    <LemonSelect {...commonSelectProps} options={intervalOptions} />
                                </Field>
                                <Field name={'frequency'} style={{ marginBottom: 0 }}>
                                    <LemonSelect {...commonSelectProps} options={frequencyOptions} />
                                </Field>

                                {subscription.frequency === 'weekly' && (
                                    <>
                                        <span>on</span>
                                        <Field name={'byweekday'} style={{ marginBottom: 0 }}>
                                            {({ value, onChange }) => (
                                                <LemonSelect
                                                    {...commonSelectProps}
                                                    options={weekdayOptions}
                                                    value={value ? value[0] : null}
                                                    onChange={(val) => onChange([val])}
                                                />
                                            )}
                                        </Field>
                                    </>
                                )}

                                {subscription.frequency === 'monthly' && (
                                    <>
                                        <span>on the</span>
                                        <Field name={'bysetpos'} style={{ marginBottom: 0 }}>
                                            {({ value, onChange }) => (
                                                <LemonSelect
                                                    {...commonSelectProps}
                                                    options={bysetposOptions}
                                                    value={value ? String(value) : null}
                                                    onChange={(val) => {
                                                        onChange(typeof val === 'string' ? parseInt(val, 10) : null)
                                                    }}
                                                />
                                            )}
                                        </Field>
                                        <Field name={'byweekday'} style={{ marginBottom: 0 }}>
                                            {({ value, onChange }) => (
                                                <LemonSelect
                                                    {...commonSelectProps}
                                                    dropdownMatchSelectWidth={false}
                                                    options={monthlyWeekdayOptions}
                                                    // "day" is a special case where it is a list of all available days
                                                    value={value ? (value.length === 1 ? value[0] : 'day') : null}
                                                    onChange={(val) =>
                                                        onChange(val === 'day' ? Object.keys(weekdayOptions) : [val])
                                                    }
                                                />
                                            )}
                                        </Field>
                                    </>
                                )}
                                <span>by</span>
                                <Field name={'start_date'}>
                                    {({ value, onChange }) => (
                                        <LemonSelect
                                            {...commonSelectProps}
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
                                </Field>
                            </div>
                        </div>
                    </section>
                )}

                <footer className="flex justify-between pt">
                    <div>
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
                    <div className="flex gap-2">
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
                    </div>
                </footer>
            </VerticalForm>
        </>
    )
}
