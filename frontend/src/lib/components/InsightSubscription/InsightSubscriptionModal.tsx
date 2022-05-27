import React from 'react'
import { useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { InsightModel } from '~/types'
import { LemonModal } from 'lib/components/LemonModal'
import { pluralize } from 'lib/utils'
import { insightSubscriptionLogic } from './insightSubscriptionLogic'

interface InsightSubscriptionModalProps {
    visible: boolean
    closeModal: () => void
    insight: Partial<InsightModel>
    canEditInsight: boolean
}

export function InsightSubscriptionModal({ visible, closeModal, insight }: InsightSubscriptionModalProps): JSX.Element {
    const logic = insightSubscriptionLogic({
        insight: insight,
    })

    const { subscriptions } = useValues(logic)
    const { insightLoading } = useValues(insightLogic)

    return (
        <LemonModal
            onCancel={closeModal}
            afterClose={closeModal}
            confirmLoading={insightLoading}
            visible={visible}
            wrapClassName="add-to-dashboard-modal"
        >
            <section>
                <h5>Manage Subscriptions</h5>
                <div className={'existing-links-info'}>
                    <strong>{subscriptions?.length}</strong>
                    {' active '}
                    {pluralize(subscriptions.length || 0, 'subscription', 'subscriptions', false)}
                </div>
            </section>
            <footer className="space-between-items pt">
                <LemonButton type="secondary" onClick={closeModal}>
                    Close
                </LemonButton>
                <LemonButton type="primary" onClick={closeModal}>
                    Add Subscription
                </LemonButton>
            </footer>
        </LemonModal>
    )
}
