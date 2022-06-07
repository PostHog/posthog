import React, { useMemo } from 'react'
import { useValues } from 'kea'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonModal } from 'lib/components/LemonModal'
import { insightSubscriptionLogic } from './insightSubscriptionLogic'
import { Field } from 'kea-forms'
import { VerticalForm } from 'lib/forms/VerticalForm'
import { DatePicker, Select, Skeleton } from 'antd'
import { membersLogic } from 'scenes/organization/Settings/membersLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { LemonSelect } from '../LemonSelect'

interface InsightSubscriptionModalProps {
    id: number | 'new'
    visible: boolean
    closeModal: () => void
    insightId: number
}

export function InsightSubscriptionModal({
    id,
    visible,
    closeModal,
    insightId,
}: InsightSubscriptionModalProps): JSX.Element {
    const logicProps = {
        id,
        insightId,
    }
    const logic = insightSubscriptionLogic({
        id,
        insightId,
    })

    const { members } = useValues(membersLogic)
    const { subscriptionLoading } = useValues(logic)
    const { preflight, preflightLoading } = useValues(preflightLogic)

    const emailOptions = useMemo(
        () =>
            members.map((member) => ({
                key: member.user.email,
                value: member.user.email,
                label: member.user.email,
            })),
        [members]
    )

    return (
        <LemonModal
            onCancel={closeModal}
            afterClose={closeModal}
            confirmLoading={subscriptionLoading}
            visible={visible}
            width={600}
        >
            <VerticalForm logic={insightSubscriptionLogic} props={logicProps} formKey="subscription" enableFormOnSubmit>
                <section>
                    <h5>{id === 'new' ? 'New' : 'Edit '} Subscription</h5>

                    {preflightLoading ? (
                        <Skeleton active paragraph={{ rows: 1 }} />
                    ) : !preflight?.email_service_available ? (
                        <p>Email unavailable!</p>
                    ) : (
                        <Field name={'emails'} label={'Emails'}>
                            <Select
                                bordered
                                mode="tags"
                                dropdownMatchSelectWidth={false}
                                data-attr="subscribed-emails"
                                options={emailOptions}
                                style={{ width: '100%' }}
                            />
                        </Field>
                    )}

                    <div className="flex gap-05 items-center">
                        <span>Every</span>
                        <Field name={'interval'}>
                            <LemonSelect type="stealth" outlined options={{}} />
                        </Field>
                        <Field name={'frequency'}>
                            <LemonSelect type="stealth" outlined options={{}} />
                        </Field>
                        <span>until</span>
                        <Field name={'end_date'}>
                            <DatePicker />
                        </Field>
                    </div>
                </section>
                <footer className="space-between-items pt">
                    <LemonButton type="secondary" onClick={closeModal}>
                        Close
                    </LemonButton>
                    <LemonButton type="primary" htmlFor="submit">
                        Save
                    </LemonButton>
                </footer>
            </VerticalForm>
        </LemonModal>
    )
}
