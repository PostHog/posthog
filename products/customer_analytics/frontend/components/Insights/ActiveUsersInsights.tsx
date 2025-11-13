import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'

import { customerAnalyticsSceneLogic } from '../../customerAnalyticsSceneLogic'
import { InsightDefinition } from '../../insightDefinitions'
import { CustomerAnalyticsQueryCard } from '../CustomerAnalyticsQueryCard'
import { EventConfigModal } from './EventConfigModal'

export function ActiveUsersInsights(): JSX.Element {
    const { activityEvent, activityEventSelectionWithDefault, activeUsersInsights, hasActivityEventChanged, tabId } =
        useValues(customerAnalyticsSceneLogic)
    const { setActivityEventSelection, saveActivityEvent, toggleEventConfigModal } =
        useActions(customerAnalyticsSceneLogic)
    const isActivityEventPageview = activityEvent === '$pageview'

    return (
        <div className="space-y-2 mb-0">
            {isActivityEventPageview && (
                <LemonBanner type="warning">
                    You are currently using pageview event to define user activity. Consider using a more specific
                    event, so that you're tracking activity accurately.
                    <div className="flex flex-row items-center gap-4 mt-2 max-w-160">
                        <ActionFilter
                            filters={activityEventSelectionWithDefault}
                            setFilters={setActivityEventSelection}
                            typeKey="customer-analytics-activity-event"
                            mathAvailability={MathAvailability.None}
                            hideDeleteBtn={true}
                            hideRename={true}
                            hideDuplicate={true}
                            hideFilter={true}
                            entitiesLimit={1}
                            actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Events]}
                            buttonCopy="Change event"
                        />
                        <LemonButton
                            type="primary"
                            disabledReason={hasActivityEventChanged ? null : 'No changes'}
                            onClick={saveActivityEvent}
                        >
                            Save activity event
                        </LemonButton>
                    </div>
                </LemonBanner>
            )}
            <div className="flex items-center gap-2 ml-1">
                <h2 className="m-0">Active Users</h2>
                {!isActivityEventPageview && (
                    <LemonButton
                        icon={<IconGear />}
                        size="small"
                        noPadding
                        onClick={() => toggleEventConfigModal()}
                        tooltip="Configure activity event"
                    />
                )}
            </div>
            <div className="grid grid-cols-[3fr_1fr] gap-2">
                {activeUsersInsights.map((insight, index) => {
                    return (
                        <CustomerAnalyticsQueryCard key={index} insight={insight as InsightDefinition} tabId={tabId} />
                    )
                })}
            </div>
            <h2 className="ml-1 -mb-2">Power Users</h2>
            <PowerUsersTable />
            <EventConfigModal />
        </div>
    )
}

function PowerUsersTable(): JSX.Element {
    const { activityEvent, tabId } = useValues(customerAnalyticsSceneLogic)
    const query = {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.HogQLQuery,
            query: hogql`
                SELECT person_id,
                       count() as event_count
                FROM events
                WHERE event = ${activityEvent}
                  and timestamp
                    > now() - interval '30 days'
                GROUP BY person_id
                ORDER BY event_count DESC
                    LIMIT 10
            `,
        },
        columns: ['person_id', 'event_count'],
    }

    return (
        <Query
            uniqueKey={`power-users-${tabId}`}
            attachTo={customerAnalyticsSceneLogic}
            query={{ ...query, showTimings: false, showOpenEditorButton: false }}
            context={{
                columns: {
                    person_id: {
                        title: 'Person',
                        render: ({ value }) => (
                            <div className="flex items-center gap-2">
                                <Link target="_blank" to={urls.personByUUID(value as string)}>
                                    {value}
                                </Link>
                            </div>
                        ),
                    },
                    event_count: {
                        title: 'Event Count',
                        render: ({ value }) => <strong>{value}</strong>,
                    },
                },
            }}
        />
    )
}
