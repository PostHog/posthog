import React, { useMemo } from 'react'
import { useActions, useValues } from 'kea'
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
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { IconChevronLeft, IconOpenInNew } from 'lib/components/icons'
import { LemonDivider, LemonInput, LemonTextArea } from 'packages/apps-common'
import { AlertMessage } from 'lib/components/AlertMessage'
import { InsightShortId } from '~/types'
import { insightSubscriptionsLogic } from '../insightSubscriptionsLogic'
import { useUnloadConfirmation } from 'kea-router'

interface EditSubscriptionProps {
    id: number | 'new'
    insightShortId: InsightShortId
    onCancel: () => void
    onDelete: () => void
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

const timeOptions: LemonSelectOptions = range(0, 23).reduce(
    (acc, x) => ({
        ...acc,
        [String(x)]: { label: `${String(x).padStart(2, '0')}:00` },
    }),
    {}
)

export function EditSubscription({ id, insightShortId, onCancel, onDelete }: EditSubscriptionProps): JSX.Element {
    const logicProps = {
        id,
        insightShortId,
    }
    const logic = insightSubscriptionLogic(logicProps)
    const subscriptionslogic = insightSubscriptionsLogic({
        insightShortId,
    })

    const { members } = useValues(membersLogic)
    const { subscription, isSubscriptionSubmitting, subscriptionChanged } = useValues(logic)
    const { resetSubscription } = useActions(logic)
    const { preflight } = useValues(preflightLogic)
    const { deleteSubscription } = useActions(subscriptionslogic)

    useUnloadConfirmation(subscriptionChanged ? 'Changes you made will be discarded.' : null, () => {
        resetSubscription()
    })

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

    const _onDelete = (): void => {
        if (id !== 'new') {
            deleteSubscription(id)
            onDelete()
        }
    }

    return (
        <>
            <VerticalForm logic={insightSubscriptionLogic} props={logicProps} formKey="subscription" enableFormOnSubmit>
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
                                    <LemonSelect
                                        type="stealth"
                                        outlined
                                        options={timeOptions}
                                        disabled={emailDisabled}
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
                        <LemonButton type="primary" htmlType="submit" loading={isSubscriptionSubmitting}>
                            {id === 'new' ? 'Create subscription' : 'Save'}
                        </LemonButton>
                    </div>
                </footer>
            </VerticalForm>
        </>
    )
}
