import React, { useMemo } from 'react'
import { useValues } from 'kea'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonModal } from 'lib/components/LemonModal'
import { insightSubscriptionLogic } from './insightSubscriptionLogic'
import { Field } from 'kea-forms'
import { VerticalForm } from 'lib/forms/VerticalForm'
import { LemonInput } from '../LemonInput/LemonInput'
import { Select, Skeleton } from 'antd'
import { membersLogic } from 'scenes/organization/Settings/membersLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

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
    const { subscription, subscriptionLoading } = useValues(logic)
    const { preflight, preflightLoading } = useValues(preflightLogic)

    const options = useMemo(
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
            wrapClassName="add-to-dashboard-modal"
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
                                options={options}
                                style={{ width: '100%' }}
                            />
                        </Field>
                    )}

                    <Field name={'schedule'} label={'Schedule'}>
                        <LemonInput />
                    </Field>
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
