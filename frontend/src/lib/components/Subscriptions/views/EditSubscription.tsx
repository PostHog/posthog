import React from 'react'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/components/LemonButton'
import { VerticalForm } from 'lib/forms/VerticalForm'
import { Select } from 'antd'
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
    intervalOptions,
    monthlyWeekdayOptions,
    SubscriptionBaseProps,
    timeOptions,
    weekdayOptions,
} from '../utils'
import { LemonDivider, LemonInput, LemonTextArea } from '@posthog/lemon-ui'

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

    const { antSelectOptions } = useValues(membersLogic)
    const { subscription, isSubscriptionSubmitting } = useValues(logic)
    const { preflight, siteUrlMisconfigured } = useValues(preflightLogic)
    const { deleteSubscription } = useActions(subscriptionslogic)

    const emailDisabled = !preflight?.email_service_available

    const _onDelete = (): void => {
        if (id !== 'new') {
            deleteSubscription(id)
            onDelete()
        }
    }

    const commonSelectProps: Partial<LemonSelectProps<LemonSelectOptions>> = {
        dropdownPlacement: 'top-start',
        type: 'stealth',
        outlined: true,
        disabled: emailDisabled,
        dropdownMatchSelectWidth: false,
    }

    return (
        <>
            <VerticalForm logic={subscriptionLogic} props={logicProps} formKey="subscription" enableFormOnSubmit>
                <header className="flex items-center border-bottom pb-05">
                    <LemonButton type="stealth" onClick={onCancel} size="small">
                        <IconChevronLeft fontSize={'1rem'} />
                        Back
                    </LemonButton>
                    <LemonDivider vertical />

                    <h4 className="mt-05">{id === 'new' ? 'New' : 'Edit '} Subscription</h4>
                </header>
                <section>
                    {subscription?.created_by ? (
                        <UserActivityIndicator
                            at={subscription.created_at}
                            by={subscription.created_by}
                            prefix={'Created'}
                            className={'mb'}
                        />
                    ) : null}
                    {emailDisabled && (
                        <AlertMessage type="error">
                            <>
                                Email subscriptions are not currently possible as this PostHog instance isn't{' '}
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
                                . In order for PostHog to work properly, please set this to the origin where your
                                instance is hosted.{' '}
                                <a
                                    target="_blank"
                                    rel="noopener"
                                    href="https://posthog.com/docs/configuring-posthog/environment-variables?utm_medium=in-product&utm_campaign=system-status-site-url-misconfig"
                                >
                                    Learn more <IconOpenInNew />
                                </a>
                            </>
                        </AlertMessage>
                    )}

                    <Field name={'title'} label={'Name'}>
                        <LemonInput placeholder="e.g. Weekly team report" disabled={emailDisabled} />
                    </Field>
                    <Field name={'target_value'} label={'Who do you want to subscribe'}>
                        {({ value, onChange }) => (
                            <>
                                <Select
                                    disabled={emailDisabled}
                                    bordered
                                    mode="tags"
                                    dropdownMatchSelectWidth={false}
                                    data-attr="subscribed-emails"
                                    options={antSelectOptions}
                                    style={{ width: '100%' }}
                                    value={value?.split(',').filter(Boolean)}
                                    onChange={(val) => onChange(val.join(','))}
                                />
                                <div className="text-small text-muted mt-05">
                                    Enter the email addresses of the users you want to share with
                                </div>
                            </>
                        )}
                    </Field>
                    <Field name={'invite_message'} label={'Message (optional)'}>
                        <LemonTextArea
                            placeholder="Your message to new subscribers (optional)"
                            disabled={emailDisabled}
                        />
                    </Field>
                    <div>
                        <div className="ant-form-item-label">
                            <label title="Recurrance">Recurrance</label>
                        </div>
                        <div className="flex gap-05 items-center border-all pa-05 flex-wrap">
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
                <footer className="space-between-items pt">
                    <div>
                        {id !== 'new' && (
                            <LemonButton type="secondary" status="danger" onClick={_onDelete}>
                                Delete subscription
                            </LemonButton>
                        )}
                    </div>
                    <div className="flex gap-05">
                        <LemonButton type="secondary" onClick={onCancel}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isSubscriptionSubmitting}
                            disabled={emailDisabled}
                        >
                            {id === 'new' ? 'Create subscription' : 'Save'}
                        </LemonButton>
                    </div>
                </footer>
            </VerticalForm>
        </>
    )
}
