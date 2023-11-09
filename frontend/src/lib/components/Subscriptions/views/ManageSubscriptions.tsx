import { useActions, useValues } from 'kea'
import { LemonButton, LemonButtonWithSideAction } from 'lib/lemon-ui/LemonButton'
import { SubscriptionType } from '~/types'
import { capitalizeFirstLetter, pluralize } from 'lib/utils'
import { IconEllipsis, IconSlack } from 'lib/lemon-ui/icons'
import { ProfileBubbles } from 'lib/lemon-ui/ProfilePicture'
import { subscriptionsLogic } from '../subscriptionsLogic'
import { SubscriptionBaseProps } from '../utils'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

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

                dropdown: {
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
                    <div className="text-link font-medium">{subscription.title}</div>
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
            <LemonModal.Header>
                <h3> Manage Subscriptions</h3>
            </LemonModal.Header>
            <LemonModal.Content>
                {subscriptionsLoading && !subscriptions.length ? (
                    <div className="space-y-2">
                        <LemonSkeleton className="w-1/2" />
                        <LemonSkeleton.Row repeat={2} />
                    </div>
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
            </LemonModal.Content>

            <LemonModal.Footer>
                <div className="flex-1">
                    {subscriptions.length ? (
                        <LemonButton type="secondary" onClick={() => onSelect('new')}>
                            Add subscription
                        </LemonButton>
                    ) : null}
                </div>
                <LemonButton type="secondary" onClick={onCancel}>
                    Close
                </LemonButton>
            </LemonModal.Footer>
        </>
    )
}
