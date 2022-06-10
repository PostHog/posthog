import React from 'react'
import { useActions, useValues } from 'kea'
import { LemonButton, LemonButtonWithSideAction } from 'lib/components/LemonButton'
import { InsightShortId, SubscriptionType } from '~/types'
import { pluralize } from 'lib/utils'
import { IconEllipsis } from 'lib/components/icons'
import { ProfileBubbles } from 'lib/components/ProfilePicture'
import { insightSubscriptionsLogic } from '../insightSubscriptionsLogic'
import { Skeleton } from 'antd'

interface SubscriptionListItemProps {
    subscription: SubscriptionType
    onClick: () => void
    onDelete?: () => void
}

const humanFrequencyMap: { [key in SubscriptionType['frequency']]: string } = {
    daily: 'day',
    weekly: 'week',
    monthly: 'month',
    yearly: 'year',
}

function summarizeSubscription(subscription: SubscriptionType): string {
    const frequency = pluralize(subscription.interval, humanFrequencyMap[subscription.frequency], undefined, false)
    return `Sent every ${subscription.interval > 1 ? subscription.interval + ' ' : ''}${frequency}`
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
            <div className="space-between-items flex-auto items-center pa-05">
                <div>
                    <div>{subscription.title}</div>
                    <div className="text-default">{summarizeSubscription(subscription)}</div>
                </div>
                <ProfileBubbles limit={4} people={subscription.target_value.split(',').map((email) => ({ email }))} />
            </div>
        </LemonButtonWithSideAction>
    )
}

interface ManageSubscriptionsProps {
    insightShortId: InsightShortId
    onCancel: () => void
    onSelect: (value: number | 'new') => void
}

export function ManageSubscriptions({ insightShortId, onCancel, onSelect }: ManageSubscriptionsProps): JSX.Element {
    const logic = insightSubscriptionsLogic({
        insightShortId,
    })

    const { subscriptions, subscriptionsLoading } = useValues(logic)
    const { deleteSubscription } = useActions(logic)

    return (
        <>
            <header className="border-bottom pb-05">
                <h4 className="mt-05">Manage Subscriptions</h4>
            </header>

            <section
                style={{
                    overflowY: 'auto',
                    maxHeight: '50vh',
                }}
            >
                {subscriptionsLoading && !subscriptions.length ? (
                    <>
                        <Skeleton paragraph={false} />
                        <Skeleton.Button active block size="large" />
                        <Skeleton.Button active block size="large" />
                        <Skeleton.Button active block size="large" />
                    </>
                ) : subscriptions.length ? (
                    <>
                        <div>
                            <strong>{subscriptions?.length}</strong>
                            {' active '}
                            {pluralize(subscriptions.length || 0, 'subscription', 'subscriptions', false)}
                        </div>
                        {subscriptions.map((sub) => (
                            <SubscriptionListItem
                                key={sub.id}
                                subscription={sub}
                                onClick={() => onSelect(sub.id)}
                                onDelete={() => deleteSubscription(sub.id)}
                            />
                        ))}
                    </>
                ) : (
                    <div className="flex-column pa items-center text-center">
                        <h3>There are no subscriptions for this insight</h3>

                        <p>Once subscriptions are created they will display here. </p>

                        <LemonButton type="primary" onClick={() => onSelect('new')}>
                            Add subscription
                        </LemonButton>
                    </div>
                )}
            </section>

            <footer className="space-between-items pt">
                <div>
                    {!!subscriptions.length ? (
                        <LemonButton type="secondary" onClick={() => onSelect('new')}>
                            Add subscription
                        </LemonButton>
                    ) : null}
                </div>
                <div className="flex gap-05">
                    <LemonButton type="secondary" onClick={onCancel}>
                        Close
                    </LemonButton>
                </div>
            </footer>
        </>
    )
}
