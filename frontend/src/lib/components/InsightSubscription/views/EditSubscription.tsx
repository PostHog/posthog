import React, { useMemo } from 'react'
import { useValues } from 'kea'
import { LemonButton } from 'lib/components/LemonButton'
import { VerticalForm } from 'lib/forms/VerticalForm'
import { Select } from 'antd'
import { membersLogic } from 'scenes/organization/Settings/membersLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { Field } from 'lib/forms/Field'
import { range } from 'lib/utils'
import { dayjs } from 'lib/dayjs'
import { LemonSelect, LemonSelectOptions } from 'lib/components/LemonSelect'
import { insightSubscriptionLogic } from '../insightSubscriptionLogic'
import { DatePicker } from 'lib/components/DatePicker'
import { SubscriptionType } from '~/types'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { IconOpenInNew } from 'lib/components/icons'
import { LemonTextArea } from 'packages/apps-common'
import { AlertMessage } from 'lib/components/AlertMessage'

interface EditSubscriptionProps {
    id: number | 'new'
    insightId: number
    onCancel: () => void
    onSubmitted: (subscription: SubscriptionType) => void
}

const intervalOptions: LemonSelectOptions = range(1, 13).reduce(
    (acc, x) => ({
        ...acc,
        [x]: { label: x },
    }),
    {}
)

const frequencyOptions: LemonSelectOptions = {
    daily: { label: 'days' },
    weekly: { label: 'weeks' },
    monthly: { label: 'months' },
}

export function EditSubscription({ id, onCancel, insightId }: EditSubscriptionProps): JSX.Element {
    const logicProps = {
        id,
        insightId,
    }
    const logic = insightSubscriptionLogic({
        id,
        insightId,
    })

    const { members } = useValues(membersLogic)
    const { subscription, isSubscriptionSubmitting } = useValues(logic)
    const { preflight } = useValues(preflightLogic)

    const emailOptions = useMemo(
        () =>
            members.map((member) => ({
                key: member.user.email,
                value: member.user.email,
                label: member.user.email,
            })),
        [members]
    )

    const emailDisabled = !preflight?.email_service_available

    return (
        <>
            <VerticalForm logic={insightSubscriptionLogic} props={logicProps} formKey="subscription" enableFormOnSubmit>
                <section>
                    <h5>{id === 'new' ? 'New' : 'Edit '} Subscription</h5>

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

                    <Field name={'target_value'} label={'Who do you want to subscribe'}>
                        {({ value, onChange }) => (
                            <>
                                <Select
                                    disabled={emailDisabled}
                                    bordered
                                    mode="tags"
                                    dropdownMatchSelectWidth={false}
                                    data-attr="subscribed-emails"
                                    options={emailOptions}
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
                    <Field name={'email_message'} label={'Message (optional)'}>
                        <LemonTextArea
                            placeholder="Your message to new subscribers (optional)"
                            disabled={emailDisabled}
                        />
                    </Field>

                    <div>
                        <div className="ant-form-item-label">
                            <label title="Recurrance">Recurrance</label>
                        </div>
                        <div className="flex gap-05 items-center border-all pa-05">
                            <span>Send every</span>
                            <Field name={'interval'} style={{ marginBottom: 0 }}>
                                <LemonSelect
                                    type="stealth"
                                    outlined
                                    options={intervalOptions}
                                    disabled={emailDisabled}
                                />
                            </Field>
                            <Field name={'frequency'} style={{ marginBottom: 0 }}>
                                <LemonSelect
                                    type="stealth"
                                    outlined
                                    options={frequencyOptions}
                                    disabled={emailDisabled}
                                />
                            </Field>
                            <span>by</span>
                            <Field name={'start_date'}>
                                {({ value, onChange }) => (
                                    <DatePicker
                                        picker="time"
                                        value={dayjs(value)}
                                        onChange={(val) => onChange(val?.toISOString())}
                                        format={'HH:mm'}
                                        disabled={emailDisabled}
                                    />
                                )}
                            </Field>
                        </div>
                    </div>
                </section>
                <footer className="space-between-items pt">
                    <LemonButton type="secondary" onClick={onCancel}>
                        Back
                    </LemonButton>
                    <LemonButton type="primary" htmlType="submit" loading={isSubscriptionSubmitting}>
                        {id === 'new' ? 'Create subscription' : 'Save'}
                    </LemonButton>
                </footer>
            </VerticalForm>
        </>
    )
}
