import { Sparkline } from 'lib/components/Sparkline'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { pluralize } from 'lib/utils/strings'

import type { PropertyUsageDetailApi, PropertyUsageUserApi } from '~/generated/core/api.schemas'
import { SceneSection } from '~/layout/scenes/components/SceneSection'

export interface PropertyDefinitionUsageProps {
    usage: PropertyUsageDetailApi | null
    loading: boolean
    failed: boolean
}

const columns: LemonTableColumns<PropertyUsageUserApi> = [
    {
        title: 'Person',
        key: 'user',
        render: function RenderUser(_, { user }) {
            return (
                <ProfilePicture
                    user={{ first_name: user.first_name, last_name: user.last_name, email: user.email }}
                    size="md"
                    showName
                />
            )
        },
    },
    {
        title: 'Queries',
        key: 'count',
        align: 'right',
        render: function RenderCount(_, { count }) {
            return <span translate="no">{count.toLocaleString()}</span>
        },
    },
    {
        title: 'Last queried',
        key: 'last_queried_at',
        render: function RenderLastQueried(_, { last_queried_at }) {
            return <TZLabel time={last_queried_at} />
        },
    },
]

export function PropertyDefinitionUsage({ usage, loading, failed }: PropertyDefinitionUsageProps): JSX.Element {
    return (
        <SceneSection
            title="Query usage"
            description="How often queries used this property in the last 30 days, including views of cached insights."
        >
            {loading ? (
                <LemonSkeleton className="w-full h-20" />
            ) : failed || !usage ? (
                <p className="text-secondary m-0">
                    Couldn't load usage for this property. Refresh the page to try again.
                </p>
            ) : usage.query_usage_30_day === 0 ? (
                <p className="text-secondary m-0">No queries used this property in the last 30 days.</p>
            ) : (
                <div className="flex flex-col gap-4" data-attr="property-definition-usage">
                    <Sparkline
                        type="bar"
                        className="w-full h-20"
                        name="Queries"
                        data={usage.daily.map((day) => day.count)}
                        labels={usage.daily.map((day) => dayjs(day.date).format('MMM D'))}
                    />
                    <div className="flex flex-col gap-1">
                        <p className="m-0">
                            <strong translate="no">{pluralize(usage.distinct_users, 'person', 'people')}</strong>
                            <span> queried this property.</span>
                        </p>
                        {usage.automated_query_usage_30_day > 0 && (
                            <p className="m-0 text-secondary">
                                <strong translate="no">
                                    {pluralize(usage.automated_query_usage_30_day, 'query', 'queries')}
                                </strong>
                                <span>
                                    {' '}
                                    ran without a signed-in user, for example from shared dashboards, subscriptions or
                                    alerts.
                                </span>
                            </p>
                        )}
                    </div>
                    <LemonTable
                        columns={columns}
                        dataSource={usage.top_users}
                        rowKey={(row) => row.user.id}
                        size="small"
                        data-attr="property-definition-usage-top-users"
                        emptyState="No current organization members queried this property."
                    />
                </div>
            )}
        </SceneSection>
    )
}
