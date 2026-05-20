import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { IconSlack } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { ProfileBubbles } from 'lib/lemon-ui/ProfilePicture'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { capitalizeFirstLetter, pluralize } from 'lib/utils'
import { isSubscriptionEnabled } from 'scenes/subscriptions/components/SubscriptionsTable'

import { SubscriptionType } from '~/types'

import { subscriptionsLogic } from '../subscriptionsLogic'
import { SubscriptionBaseProps } from '../utils'

interface SubscriptionListItemProps {
    subscription: SubscriptionType
    onClick: () => void
    onDelete?: () => void
    onDeliver?: () => void
    onToggleEnabled?: (enabled: boolean) => void
    isDelivering?: boolean
    isToggling?: boolean
}

export function SubscriptionListItem({
    subscription,
    onClick,
    onDelete,
    onDeliver,
    onToggleEnabled,
    isDelivering,
    isToggling,
}: SubscriptionListItemProps): JSX.Element {
    const selectedInsightsCount = subscription.dashboard_export_insights?.length
    const enabled = isSubscriptionEnabled(subscription)
    const sideActionBusy = isDelivering || isToggling

    return (
        <LemonButton
            type="secondary"
            onClick={onClick}
            data-attr="subscription-list-item"
            fullWidth
            sideAction={{
                icon: sideActionBusy ? <Spinner /> : <IconEllipsis />,
                disabled: sideActionBusy,
                dropdown: {
                    overlay: (
                        <>
                            {onToggleEnabled && (
                                <LemonButton
                                    onClick={() => onToggleEnabled(!enabled)}
                                    data-attr="subscription-list-item-toggle-enabled"
                                    fullWidth
                                    disabled={isToggling}
                                >
                                    {enabled ? 'Disable subscription' : 'Enable subscription'}
                                </LemonButton>
                            )}
                            {onDeliver && enabled && (
                                <LemonButton
                                    onClick={onDeliver}
                                    data-attr="subscription-list-item-manual-deliver"
                                    fullWidth
                                    disabled={isDelivering}
                                >
                                    Test delivery
                                </LemonButton>
                            )}
                            {onDelete && (
                                <LemonButton
                                    onClick={onDelete}
                                    data-attr="subscription-list-item-delete"
                                    status="danger"
                                    fullWidth
                                >
                                    Delete subscription
                                </LemonButton>
                            )}
                        </>
                    ),
                },
            }}
        >
            <div className="flex justify-between flex-auto items-center p-2">
                <div>
                    <div className={`font-medium ${enabled ? 'text-link' : 'text-muted'}`}>{subscription.title}</div>
                    <div className="text-sm text-text-3000">
                        {capitalizeFirstLetter(subscription.summary)}
                        {selectedInsightsCount
                            ? ` · ${pluralize(selectedInsightsCount, 'insight', 'insights', true)}`
                            : null}
                    </div>
                    {!enabled ? (
                        <LemonTag type="danger" size="small" className="mt-1">
                            Disabled
                        </LemonTag>
                    ) : subscription.next_delivery_date ? (
                        <div className="text-xs text-secondary">
                            Next delivery: {dayjs(subscription.next_delivery_date).format('ddd, MMM D [at] HH:mm')}
                        </div>
                    ) : null}
                </div>
                {subscription.target_type === 'email' ? (
                    <ProfileBubbles
                        limit={4}
                        people={subscription.target_value.split(',').map((email) => ({ email }))}
                    />
                ) : null}
                {subscription.target_type === 'slack' ? <IconSlack /> : null}
            </div>
        </LemonButton>
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

    const { subscriptions, subscriptionsLoading, deliveringSubscriptionId, togglingEnabledId } = useValues(logic)
    const { deleteSubscription, deliverSubscription, setSubscriptionEnabled } = useActions(logic)

    const subscriptionResourceNoun = !insightShortId && dashboardId ? 'dashboard' : 'insight'

    return (
        <>
            <LemonModal.Header>
                <h3> Manage Subscriptions</h3>
            </LemonModal.Header>
            <LemonModal.Content>
                {subscriptionsLoading && !subscriptions.length ? (
                    <div className="deprecated-space-y-2">
                        <LemonSkeleton className="w-1/2 h-4" />
                        <LemonSkeleton.Row repeat={2} />
                    </div>
                ) : subscriptions.length ? (
                    <div className="deprecated-space-y-2">
                        <div>
                            <strong>{subscriptions?.length}</strong>{' '}
                            {pluralize(subscriptions.length || 0, 'subscription', 'subscriptions', false)}
                        </div>

                        <div className="max-h-[50vh] overflow-y-auto flex flex-col gap-2">
                            {subscriptions.map((sub) => (
                                <SubscriptionListItem
                                    key={sub.id}
                                    subscription={sub}
                                    onClick={() => onSelect(sub.id)}
                                    onDelete={() => deleteSubscription(sub.id)}
                                    onDeliver={() => deliverSubscription(sub.id)}
                                    onToggleEnabled={(enabled) => setSubscriptionEnabled(sub.id, enabled)}
                                    isDelivering={deliveringSubscriptionId === sub.id}
                                    isToggling={togglingEnabledId === sub.id}
                                />
                            ))}
                        </div>
                    </div>
                ) : (
                    <div className="flex flex-col p-4 items-center text-center">
                        <h3>There are no subscriptions for this {subscriptionResourceNoun}</h3>

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
