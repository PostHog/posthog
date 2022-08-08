import React from 'react'
import { ManageSubscriptions } from './views/ManageSubscriptions'
import { EditSubscription } from './views/EditSubscription'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { LemonButton, LemonButtonWithPopup } from '@posthog/lemon-ui'
import { SubscriptionBaseProps, urlForSubscription, urlForSubscriptions } from './utils'
import { PayGatePage } from '../PayGatePage/PayGatePage'
import { AvailableFeature } from '~/types'
import { userLogic } from 'scenes/userLogic'
import { Spinner } from '../Spinner/Spinner'
import { LemonModal } from '../LemonModal'

export interface SubscriptionsModalProps extends SubscriptionBaseProps {
    visible: boolean
    closeModal: () => void
    subscriptionId: number | 'new' | null
    inline?: boolean
}

export function SubscriptionsModal(props: SubscriptionsModalProps): JSX.Element {
    const { closeModal, dashboardId, insightShortId, subscriptionId, visible, inline } = props
    const { push } = useActions(router)
    const { hasAvailableFeature, userLoading } = useValues(userLogic)

    if (userLoading) {
        return <Spinner />
    }
    return (
        <LemonModal onClose={closeModal} isOpen={visible} width={650} simple title="" inline={inline}>
            {hasAvailableFeature(AvailableFeature.SUBSCRIPTIONS) ? (
                !subscriptionId ? (
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
                )
            ) : (
                <div className="p-10">
                    <PayGatePage
                        featureKey={AvailableFeature.SUBSCRIPTIONS}
                        header={
                            <>
                                Introducing <span className="highlight">Subscriptions</span>!
                            </>
                        }
                        caption="Get Insight or Dashboard reports directly to your inbox!"
                        docsLink="https://posthog.com/docs/user-guides/subscriptions"
                    />
                </div>
            )}
        </LemonModal>
    )
}

export function SubscribeButton(props: SubscriptionBaseProps): JSX.Element {
    const { push } = useActions(router)

    return (
        <LemonButtonWithPopup
            status="stealth"
            fullWidth
            popup={{
                actionable: true,
                placement: 'right-start',
                overlay: (
                    <>
                        <LemonButton onClick={() => push(urlForSubscription('new', props))} status="stealth" fullWidth>
                            New subscription
                        </LemonButton>
                        <LemonButton onClick={() => push(urlForSubscriptions(props))} status="stealth" fullWidth>
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
