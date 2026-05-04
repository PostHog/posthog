import { Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import type { SubscriptionApi } from '~/generated/core/api.schemas'
import type { HedgehogConfig, MinimalHedgehogConfig } from '~/types'

import { SubscriptionDestinationCell } from './SubscriptionDestinationCell'
import { TARGET_TYPE_LABEL } from './subscriptionLabels'
import { subscriptionResourceLabel, subscriptionResourceViewUrl } from './SubscriptionsTable'

export function SubscriptionSummary({ sub }: { sub: SubscriptionApi }): JSX.Element {
    const resourceHref = subscriptionResourceViewUrl(sub)
    const resourceFieldLabel = sub.insight ? 'Insight' : sub.dashboard ? 'Dashboard' : 'Resource'
    const resourceDisplayName = subscriptionResourceLabel(sub, 'summary')

    return (
        <div className="flex w-full min-w-0 flex-col gap-4">
            <dl className="grid w-full min-w-0 grid-cols-1 gap-x-10 gap-y-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                <div>
                    <dt className="text-sm text-secondary">{resourceFieldLabel}</dt>
                    <dd className="font-medium min-w-0">
                        {resourceHref && resourceDisplayName !== '—' ? (
                            <Link to={resourceHref} className="truncate block">
                                {resourceDisplayName}
                            </Link>
                        ) : resourceDisplayName !== '—' ? (
                            <span className="truncate block">{resourceDisplayName}</span>
                        ) : (
                            <span className="text-secondary">—</span>
                        )}
                    </dd>
                </div>
                <div>
                    <dt className="text-sm text-secondary">Channel</dt>
                    <dd className="font-medium">{TARGET_TYPE_LABEL[sub.target_type] ?? sub.target_type}</dd>
                </div>
                <div>
                    <dt className="text-sm text-secondary">Destination</dt>
                    <dd className="min-w-0">
                        <SubscriptionDestinationCell sub={sub} />
                    </dd>
                </div>
                <div className="min-w-0">
                    <dt className="text-sm text-secondary">Recurrence</dt>
                    <dd className="break-words font-medium">{sub.summary || '—'}</dd>
                </div>
                <div>
                    <dt className="text-sm text-secondary">Next delivery</dt>
                    <dd className="font-medium">
                        {sub.next_delivery_date ? <TZLabel time={sub.next_delivery_date} /> : '—'}
                    </dd>
                </div>
                <div>
                    <dt className="text-sm text-secondary">Created by</dt>
                    <dd className="font-medium">
                        <ProfilePicture
                            user={{
                                email: sub.created_by.email,
                                first_name: sub.created_by.first_name,
                                last_name: sub.created_by.last_name,
                                hedgehog_config: (sub.created_by.hedgehog_config ?? undefined) as
                                    | MinimalHedgehogConfig
                                    | HedgehogConfig
                                    | undefined,
                            }}
                            size="md"
                            showName
                        />
                    </dd>
                </div>
                <div>
                    <dt className="text-sm text-secondary">Created</dt>
                    <dd className="font-medium">
                        <TZLabel time={sub.created_at} />
                    </dd>
                </div>
            </dl>
        </div>
    )
}
