import React from 'react'
import { InsightModel, InsightShortId } from '~/types'
import { LemonModal } from 'lib/components/LemonModal'
import { ManageSubscriptions } from './views/ManageSubscriptions'
import { EditSubscription } from './views/EditSubscription'
import { useActions } from 'kea'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'

interface InsightSubscriptionModalProps {
    visible: boolean
    closeModal: () => void
    insight: Partial<InsightModel>
    subscriptionId: number | 'new' | null
}

export function InsightSubscriptionsModal({
    visible,
    closeModal,
    insight,
    subscriptionId,
}: InsightSubscriptionModalProps): JSX.Element {
    const { push } = useActions(router)

    return (
        <>
            <LemonModal onCancel={closeModal} afterClose={closeModal} visible={visible} width={600}>
                {!subscriptionId || !insight.id ? (
                    <ManageSubscriptions
                        insight={insight}
                        onCancel={closeModal}
                        onSelect={(id) =>
                            push(urls.insightSubcription(insight.short_id as InsightShortId, id.toString()))
                        }
                    />
                ) : (
                    <EditSubscription
                        id={subscriptionId}
                        insightId={insight.id}
                        onCancel={() => push(urls.insightSubcriptions(insight.short_id as InsightShortId))}
                        onSubmitted={() => {
                            console.log('sibmited')
                        }}
                    />
                )}
            </LemonModal>
        </>
    )
}
