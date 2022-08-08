import React from 'react'
import { useActions, useValues } from 'kea'
import { LemonButton, LemonButtonWithSideAction } from 'lib/components/LemonButton'
import { SubscriptionType } from '~/types'
import { capitalizeFirstLetter, pluralize } from 'lib/utils'
import { IconEllipsis, IconSlack } from 'lib/components/icons'
import { ProfileBubbles } from 'lib/components/ProfilePicture'
import { subscriptionsLogic } from '../subscriptionsLogic'
import { Skeleton } from 'antd'
import { SubscriptionBaseProps } from '../utils'
import { LemonModalV2 } from 'lib/components/LemonModalV2'

interface SubscriptionListItemProps {
    subscription: SubscriptionType
    onClick: () => void
    onDelete?: () => void
}

export function SubscriptionListItem({ subscription, onClick, onDelete }: SubscriptionListItemProps): JSX.Element {
    return (
        <LemonButtonWithSideAction
            type="secondary"
            status="stealth"
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
            <div className="flex justify-between flex-auto items-center p-2">
                <div>
                    <div className="text-primary font-medium">{subscription.title}</div>
                    <div className="text-sm text-default">{capitalizeFirstLetter(subscription.summary)}</div>
                </div>
                {subscription.target_type === 'email' ? (
                    <ProfileBubbles
                        limit={4}
                        people={subscription.target_value.split(',').map((email) => ({ email }))}
                    />
                ) : null}
                {subscription.target_type === 'slack' ? <IconSlack /> : null}
            </div>
        </LemonButtonWithSideAction>
    )
}

interface ManageSubscriptionsProps extends SubscriptionBaseProps {
    onCancel: () => void
    onSelect: (value: number | 'new') => void
}

export function ManageSubscriptions({
    insightShortId,
    dashboardId,
    onCancel,
    onSelect,
}: ManageSubscriptionsProps): JSX.Element {
    const logic = subscriptionsLogic({
        insightShortId,
        dashboardId,
    })

    const { subscriptions, subscriptionsLoading } = useValues(logic)
    const { deleteSubscription } = useActions(logic)

    return (
        <>
            <LemonModalV2.Header>
                <h3> Manage Subscriptions</h3>
            </LemonModalV2.Header>
            <LemonModalV2.Content>
                {subscriptionsLoading && !subscriptions.length ? (
                    <>
                        <Skeleton paragraph={false} />
                        <Skeleton.Button active block size="large" />
                        <Skeleton.Button active block size="large" />
                        <Skeleton.Button active block size="large" />
                    </>
                ) : subscriptions.length ? (
                    <div className="space-y-2">
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
                    </div>
                ) : (
                    <div className="flex flex-col p-4 items-center text-center">
                        <h3>There are no subscriptions for this insight</h3>

                        <p>Once subscriptions are created they will display here. </p>

                        <LemonButton type="primary" onClick={() => onSelect('new')}>
                            Add subscription
                        </LemonButton>
                    </div>
                )}
            </LemonModalV2.Content>

            <LemonModalV2.Footer>
                <div className="flex-1">
                    {!!subscriptions.length ? (
                        <LemonButton type="secondary" onClick={() => onSelect('new')}>
                            Add subscription
                        </LemonButton>
                    ) : null}
                </div>
                <LemonButton type="secondary" onClick={onCancel}>
                    Close
                </LemonButton>
            </LemonModalV2.Footer>
        </>
    )
}
