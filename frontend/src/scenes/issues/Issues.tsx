import {
    //LemonButton,
    LemonDivider,
    LemonTag,
} from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { Query } from '~/queries/Query/Query'
import { EventsQuery, NodeKind } from '~/queries/schema'
import { ChartDisplayType, InsightType } from '~/types'
import { useState } from 'react'
import { DateRange } from '~/queries/nodes/DataNode/DateRange'
import { EventPropertyFilters } from '~/queries/nodes/EventsNode/EventPropertyFilters'
// import { IconSettings } from 'lib/lemon-ui/icons'
// import { openSessionRecordingSettingsDialog } from 'scenes/session-recordings/settings/SessionRecordingSettings'

export const Issues = (): JSX.Element => {
    const [query, setQuery] = useState<EventsQuery>({
        kind: NodeKind.EventsQuery,
        select: ['*', 'event', 'person', 'timestamp'],
        properties: [],
        fixedProperties: [
            // todo fix by defined user event/action
        ],
        after: '-24h',
        limit: 100,
    })

    return (
        <div>
            <PageHeader
                title={
                    <div className="flex items-center gap-2">
                        Issues
                        <LemonTag type="warning" className="uppercase">
                            BETA
                        </LemonTag>
                    </div>
                }
                buttons={
                    <>
                        {/*<LemonButton type="secondary" icon={<IconSettings />} onClick={() => openIssuesConfigDialog()}>*/}
                        {/*    Configure*/}
                        {/*</LemonButton>*/}
                    </>
                }
            />

            <div className={'flex flex-row spacex-2'}>
                <DateRange query={query} setQuery={setQuery} />,
                <EventPropertyFilters query={query} setQuery={(q) => setQuery(q as EventsQuery)} />,
            </div>
            <LemonDivider />
            <h2>Issue incidence</h2>
            <Query
                query={{
                    kind: NodeKind.LegacyQuery,
                    filters: {
                        insight: InsightType.TRENDS,
                        date_from: query.after,
                        events: [
                            {
                                id: '$pageview',
                                math: 'avg_count_per_actor',
                                name: '$pageview',
                                type: 'events',
                                order: 0,
                            },
                        ],
                        display: ChartDisplayType.ActionsLineGraph,
                        interval: 'day',
                        properties: query.properties,
                        // todo need to get fixed properties into here too
                    },
                }}
            />
            <LemonDivider />
            <h2>Your issues</h2>
            <Query
                query={{
                    kind: NodeKind.DataTableNode,
                    full: false,
                    showOpenEditorButton: false,
                    source: query,
                }}
            />
        </div>
    )
}

export const scene: SceneExport = {
    component: Issues,
}
