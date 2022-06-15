import React from 'react'
import { LemonModal } from 'lib/components/LemonModal'
import { ManageSubscriptions } from './views/ManageSubscriptions'
import { EditSubscription } from './views/EditSubscription'
import { useActions } from 'kea'
import { router } from 'kea-router'
import { LemonButton, LemonButtonWithPopup } from '@posthog/lemon-ui'
import { SubscriptionBaseProps, urlForSubscription, urlForSubscriptions } from './utils'

export interface SubscriptionsModalProps extends SubscriptionBaseProps {
    visible: boolean
    closeModal: () => void
    subscriptionId: number | 'new' | null
}

export function SubscriptionsModal(props: SubscriptionsModalProps): JSX.Element {
    const { visible, closeModal, dashboardId, insightShortId, subscriptionId } = props
    const { push } = useActions(router)

    return (
        <>
            <LemonModal onCancel={closeModal} afterClose={closeModal} visible={visible} width={650}>
                {!subscriptionId ? (
                    <ManageSubscriptions
                        insightShortId={insightShortId}
                        dashboardId={dashboardId}
                        onCancel={closeModal}
                        onSelect={(id) => push(urlForSubscription(id, props))}
                    />
                ) : (
                    <EditSubscription
                        id={subscriptionId}
                        insightShortId={insightShortId}
                        dashboardId={dashboardId}
                        onCancel={() => push(urlForSubscriptions(props))}
                        onDelete={() => push(urlForSubscriptions(props))}
                    />
                )}
            </LemonModal>
        </>
    )
}

export function SubscribeButton(props: SubscriptionBaseProps): JSX.Element {
    const { push } = useActions(router)

    return (
        <LemonButtonWithPopup
            type="stealth"
            fullWidth
            popup={{
                actionable: true,
                placement: 'right-start',
                overlay: (
                    <>
                        <LemonButton onClick={() => push(urlForSubscription('new', props))} type="stealth" fullWidth>
                            New subscription
                        </LemonButton>
                        <LemonButton onClick={() => push(urlForSubscriptions(props))} type="stealth" fullWidth>
                            Manage subscriptions
                        </LemonButton>
                    </>
                ),
            }}
        >
            Subscribe
        </LemonButtonWithPopup>
    )
}
