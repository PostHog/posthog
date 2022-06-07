import React, { useState } from 'react'
import { useValues } from 'kea'
import { LemonButton, LemonButtonWithSideAction } from 'lib/components/LemonButton'
import { InsightModel, SubscriptionType } from '~/types'
import { LemonModal } from 'lib/components/LemonModal'
import { pluralize } from 'lib/utils'
import { insightSubscriptionsLogic } from './insightSubscriptionsLogic'
import { InsightSubscriptionModal } from './InsightSubscriptionModal'
import { IconEllipsis, IconPlus } from '../icons'
import { ProfileBubbles } from '../ProfilePicture'

interface SubscriptionListItemProps {
    subscription: SubscriptionType
    onClick: () => void
    onDelete?: () => void
}

export function SubscriptionListItem({ subscription, onClick, onDelete }: SubscriptionListItemProps): JSX.Element {
    return (
        <LemonButtonWithSideAction
            type="stealth"
            outlined
            onClick={() => onClick()}
            data-attr="subscription-list-item"
            fullWidth
            sideAction={{
                icon: <IconEllipsis />,

                popup: {
                    overlay: (
                        <>
                            {onDelete && (
                                <LemonButton
                                    onClick={() => onDelete()}
                                    data-attr="subscription-list-item-delete"
                                    type="stealth"
                                    status="danger"
                                    fullWidth
                                >
                                    Delete Subscription
                                </LemonButton>
                            )}
                        </>
                    ),
                },
            }}
        >
            <span className="space-between-items flex-auto items-center">
                <span>{subscription.title}</span>
                <ProfileBubbles limit={4} people={subscription.emails.map((email) => ({ email }))} />
            </span>
        </LemonButtonWithSideAction>
    )
}

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
    const logic = insightSubscriptionsLogic({
        insight: insight,
    })

    const [selectedSubscription, setSelectedSubscription] = useState<number | 'new'>()

    const { subscriptions, subscriptionsLoading } = useValues(logic)

    // subscriptions = [
    //     {
    //         id: 123,
    //         emails: ['ben@posthog.com', 'james@posthog.com'],
    //         insight: insight.id || 1,
    //         schedule: '0 0 0 0 ',
    //         created_at: '',
    //         title: 'Subscription 1',
    //         updated_at: '',
    //     },
    //     {
    //         id: 456,
    //         emails: ['james@posthog.com'],
    //         insight: insight.id || 1,
    //         schedule: '0 0 0 0 ',
    //         created_at: '',
    //         title: 'Subscription 2',
    //         updated_at: '',
    //     },
    // ]

    return (
        <>
            {!selectedSubscription || !insight.id ? (
                <LemonModal
                    onCancel={closeModal}
                    afterClose={closeModal}
                    confirmLoading={subscriptionsLoading}
                    visible={visible}
                >
                    <section>
                        <h5>Manage Subscriptions</h5>
                        <div className={'existing-links-info'}>
                            <strong>{subscriptions?.length}</strong>
                            {' active '}
                            {pluralize(subscriptions.length || 0, 'subscription', 'subscriptions', false)}
                        </div>
                    </section>
                    <section>
                        {subscriptions.length ? (
                            subscriptions.map((sub) => (
                                <SubscriptionListItem
                                    key={sub.id}
                                    subscription={sub}
                                    onClick={() => setSelectedSubscription(sub.id)}
                                    onDelete={() => console.log(sub.id)}
                                />
                            ))
                        ) : (
                            <div className="flex-column pa items-center gap text-center">
                                <h2>Subscribe to Insights</h2>

                                <p>Receive scheduled reports directly to your inbox for your most important Insights</p>
                            </div>
                        )}
                    </section>

                    <footer className="space-between-items pt">
                        <LemonButton type="secondary" onClick={closeModal}>
                            Close
                        </LemonButton>
                        <LemonButton type="primary" onClick={() => setSelectedSubscription('new')} icon={<IconPlus />}>
                            Add subscription
                        </LemonButton>
                    </footer>
                </LemonModal>
            ) : (
                <InsightSubscriptionModal
                    id={selectedSubscription}
                    insightId={insight.id}
                    visible={visible}
                    closeModal={closeModal}
                />
            )}
        </>
    )
}
