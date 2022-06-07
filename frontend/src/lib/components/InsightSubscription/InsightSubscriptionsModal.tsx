import React, { useState } from 'react'
import { InsightModel } from '~/types'
import { LemonModal } from 'lib/components/LemonModal'
import { ManageSubscriptions } from './views/ManageSubscriptions'
import { EditSubscription } from './views/EditSubscription'

interface InsightSubscriptionModalProps {
    visible: boolean
    closeModal: () => void
    insight: Partial<InsightModel>
}

export function InsightSubscriptionsModal({
    visible,
    closeModal,
    insight,
}: InsightSubscriptionModalProps): JSX.Element {
    const [selectedSubscription, setSelectedSubscription] = useState<number | 'new'>()

    return (
        <>
            <LemonModal onCancel={closeModal} afterClose={closeModal} visible={visible} width={600}>
                {!selectedSubscription || !insight.id ? (
                    <ManageSubscriptions insight={insight} onCancel={closeModal} onSelect={setSelectedSubscription} />
                ) : (
                    <EditSubscription
                        id={selectedSubscription}
                        insightId={insight.id}
                        onCancel={() => setSelectedSubscription(undefined)}
                        onSubmitted={() => {
                            console.log('sibmited')
                        }}
                    />
                )}
            </LemonModal>
        </>
    )
}
