import { LemonButton, LemonDivider, LemonTag } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { Query } from '~/queries/Query/Query'
import { EventsQuery, NodeKind } from '~/queries/schema'
import { ChartDisplayType, InsightType } from '~/types'
import { DateRange } from '~/queries/nodes/DataNode/DateRange'
import { EventPropertyFilters } from '~/queries/nodes/EventsNode/EventPropertyFilters'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { IconSettings } from 'lib/lemon-ui/icons'
import { LemonEventName } from 'scenes/actions/EventName'
import { useActions, useValues } from 'kea'
import { issuesLogic } from 'scenes/issues/issuesLogic'

export function IssuesSettings(): JSX.Element {
    const { issueEvent } = useValues(issuesLogic)
    const { setIssueEvent } = useActions(issuesLogic)
    return (
        <div className={'flex flex-col gap-2'}>
            <h2>Issues settings</h2>
            <div>
                Configure which events are used for issue reporting. If this is not set we use <code>$bug_report</code>
            </div>
            <LemonEventName value={issueEvent} onChange={(value: string) => setIssueEvent(value)} />
        </div>
    )
}

export function openIssuesConfigDialog(): void {
    LemonDialog.open({
        title: 'Issue settings',
        content: <IssuesSettings />,
        width: 600,
        primaryButton: {
            children: 'Done',
        },
    })
}

export const Issues = (): JSX.Element => {
    const { query, issueEvent, tableQuery } = useValues(issuesLogic)
    const { setQuery } = useActions(issuesLogic)

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
                        <LemonButton type="secondary" icon={<IconSettings />} onClick={() => openIssuesConfigDialog()}>
                            Configure
                        </LemonButton>
                    </>
                }
            />

            <div className={'flex flex-row space-x-2'}>
                <DateRange query={query} setQuery={setQuery} />
                <EventPropertyFilters query={query} setQuery={(q) => setQuery(q as EventsQuery)} />
            </div>
            <LemonDivider />
            <h2>Issue count</h2>
            <Query
                query={{
                    kind: NodeKind.LegacyQuery,
                    filters: {
                        insight: InsightType.TRENDS,
                        date_from: query.after,
                        events: [
                            {
                                id: issueEvent,
                                name: issueEvent,
                                type: 'events',
                                order: 0,
                            },
                        ],
                        display: ChartDisplayType.ActionsBar,
                        properties: query.properties,
                    },
                }}
                context={{
                    emptyStateHeading: 'Yay! No issues found!',
                    emptyStateDetail: '',
                }}
            />
            <LemonDivider />
            <h2>Open issues</h2>
            <Query query={tableQuery} context={{ emptyStateHeading: 'Yay! No issues found', emptyStateDetail: '' }} />
        </div>
    )
}

export const scene: SceneExport = {
    component: Issues,
}
