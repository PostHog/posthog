import React from 'react'
import { useActions, useValues } from 'kea'
import { LemonButton, LemonButtonWithSideAction } from 'lib/components/LemonButton'
import { InsightModel, SubscriptionType } from '~/types'
import { pluralize } from 'lib/utils'
import { IconEllipsis, IconPlus } from 'lib/components/icons'
import { ProfileBubbles } from 'lib/components/ProfilePicture'
import { insightSubscriptionsLogic } from '../insightSubscriptionsLogic'
import { Skeleton } from 'antd'

interface SubscriptionListItemProps {
    subscription: SubscriptionType
    onClick: () => void
    onDelete?: () => void
}

export function SubscriptionListItem({ subscription, onClick, onDelete }: SubscriptionListItemProps): JSX.Element {
    return (
        <LemonButtonWithSideAction
            type="secondary"
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
            <span className="space-between-items flex-auto items-center pa-05">
                <span>{subscription.title}</span>
                <ProfileBubbles limit={4} people={subscription.target_value.split(',').map((email) => ({ email }))} />
            </span>
        </LemonButtonWithSideAction>
    )
}

interface ManageSubscriptionsProps {
    insight: Partial<InsightModel>
    onCancel: () => void
    onSelect: (value: number | 'new') => void
}

export function ManageSubscriptions({ insight, onCancel, onSelect }: ManageSubscriptionsProps): JSX.Element {
    const logic = insightSubscriptionsLogic({
        insight: insight,
    })

    const { subscriptions, subscriptionsLoading } = useValues(logic)
    const { deleteSubscription } = useActions(logic)

    return (
        <>
            <section>
                <h5>Manage Subscriptions</h5>
                <div className={'existing-links-info'}>
                    <strong>{subscriptions?.length}</strong>
                    {' active '}
                    {pluralize(subscriptions.length || 0, 'subscription', 'subscriptions', false)}
                </div>
            </section>
            <section>
                {subscriptionsLoading ? (
                    <>
                        <Skeleton.Button active block size="large" />
                        <Skeleton.Button active block size="large" />
                        <Skeleton.Button active block size="large" />
                    </>
                ) : subscriptions.length ? (
                    subscriptions.map((sub) => (
                        <SubscriptionListItem
                            key={sub.id}
                            subscription={sub}
                            onClick={() => onSelect(sub.id)}
                            onDelete={() => deleteSubscription(sub.id)}
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
                <LemonButton type="secondary" onClick={onCancel}>
                    Close
                </LemonButton>
                <LemonButton type="primary" onClick={() => onSelect('new')} icon={<IconPlus />}>
                    Add subscription
                </LemonButton>
            </footer>
        </>
    )
}
