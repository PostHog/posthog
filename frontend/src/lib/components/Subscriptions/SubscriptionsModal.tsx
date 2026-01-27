import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, DashboardType, InsightShortId } from '~/types'

import { PayGateMini } from '../PayGateMini/PayGateMini'
import { SubscriptionBaseProps, urlForSubscription, urlForSubscriptions } from './utils'
import { EditSubscription } from './views/EditSubscription'
import { ManageSubscriptions } from './views/ManageSubscriptions'

export interface SubscriptionsModalProps {
    isOpen: boolean
    closeModal: () => void
    subscriptionId: number | 'new' | null
    inline?: boolean
    insightShortId?: InsightShortId
    dashboard?: DashboardType<any> | null
}

export function SubscriptionsModal(props: SubscriptionsModalProps): JSX.Element {
    const { closeModal, dashboard, insightShortId, subscriptionId, isOpen, inline } = props
    const dashboardId = dashboard?.id
    const baseProps: SubscriptionBaseProps = { insightShortId, dashboardId }
    const { push } = useActions(router)
    const { userLoading } = useValues(userLogic)

    if (userLoading) {
        return <Spinner className="text-2xl" />
    }
    return (
        <LemonModal onClose={closeModal} isOpen={isOpen} width={600} simple title="" inline={inline}>
            <PayGateMini
                feature={AvailableFeature.SUBSCRIPTIONS}
                handleSubmit={closeModal}
                background={false}
                className="py-8"
                docsLink="https://posthog.com/docs/user-guides/subscriptions"
            >
                {!subscriptionId ? (
                    <ManageSubscriptions
                        {...baseProps}
                        onCancel={closeModal}
                        onSelect={(id) => push(urlForSubscription(id, baseProps))}
                    />
                ) : (
                    <EditSubscription
                        id={subscriptionId}
                        insightShortId={insightShortId}
                        dashboard={dashboard}
                        onCancel={() => push(urlForSubscriptions(baseProps))}
                        onDelete={() => push(urlForSubscriptions(baseProps))}
                    />
                )}
            </PayGateMini>
        </LemonModal>
    )
}
