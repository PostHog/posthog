import React from 'react'
import { InsightShortId } from '~/types'
import { LemonModal } from 'lib/components/LemonModal'
import { ManageSubscriptions } from './views/ManageSubscriptions'
import { EditSubscription } from './views/EditSubscription'
import { useActions } from 'kea'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'

interface InsightSubscriptionModalProps {
    visible: boolean
    closeModal: () => void
    insightShortId: InsightShortId
    subscriptionId: number | 'new' | null
}

export function InsightSubscriptionsModal({
    visible,
    closeModal,
    insightShortId,
    subscriptionId,
}: InsightSubscriptionModalProps): JSX.Element {
    const { push } = useActions(router)

    return (
        <>
            <LemonModal onCancel={closeModal} afterClose={closeModal} visible={visible} width={650}>
                {!subscriptionId ? (
                    <ManageSubscriptions
                        insightShortId={insightShortId}
                        onCancel={closeModal}
                        onSelect={(id) => push(urls.insightSubcription(insightShortId, id.toString()))}
                    />
                ) : (
                    <EditSubscription
                        id={subscriptionId}
                        insightShortId={insightShortId}
                        onCancel={() => push(urls.insightSubcriptions(insightShortId))}
                        onDelete={() => push(urls.insightSubcriptions(insightShortId))}
                    />
                )}
            </LemonModal>
        </>
    )
}
