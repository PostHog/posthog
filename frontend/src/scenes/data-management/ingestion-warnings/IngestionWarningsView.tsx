import React from 'react'
import { useValues } from 'kea'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { PageHeader } from 'lib/components/PageHeader'
import { DataManagementPageTabs, DataManagementTab } from 'scenes/data-management/DataManagementPageTabs'
import { IngestionWarning, ingestionWarningsLogic, IngestionWarningSummary } from './ingestionWarningsLogic'
import { LemonTable } from 'lib/components/LemonTable'
import { TZLabel } from 'lib/components/TimezoneAware'
import { Link } from 'lib/components/Link'
import { WarningEventsGraph } from './WarningEventsGraph'

export const scene: SceneExport = {
    component: IngestionWarningsView,
    logic: ingestionWarningsLogic,
}

const WARNING_TYPE_TO_DESCRIPTION = {
    cannot_merge_already_identified: 'Refused to merge an already identified user via $identify or $create_alias call',
    cannot_merge_with_illegal_distinct_id:
        'Refused to merge with an illegal distinct_id via $identify or $create_alias call',
    cannot_merge_attepts_exhausted: 'Merge via $identify or $create_alias call failed',
    skipping_event_invalid_uuid: 'Refused to process event with invalid uuid',
}

const WARNING_TYPE_RENDERER = {
    cannot_merge_already_identified: function Render(warning: IngestionWarning): JSX.Element {
        const details = warning.details as {
            sourcePersonDistinctId: string
            targetPersonDistinctId: string
        }
        return (
            <>
                Refused to merge already identified person{' '}
                <Link to={urls.person(details.sourcePersonDistinctId)}>{details.sourcePersonDistinctId}</Link> into{' '}
                <Link to={urls.person(details.targetPersonDistinctId)}>{details.targetPersonDistinctId}</Link> via an
                $identify or $create_alias call
            </>
        )
    },
    cannot_merge_with_illegal_distinct_id: function Render(warning: IngestionWarning): JSX.Element {
        const details = warning.details as {
            illegalDistinctId: string
            otherDistinctId: string
        }
        return (
            <>
                Refused to merge an illegal distinct_id{' '}
                <Link to={urls.person(details.illegalDistinctId)}>{details.illegalDistinctId}</Link> with{' '}
                <Link to={urls.person(details.otherDistinctId)}>{details.otherDistinctId}</Link> via an $identify or
                $create_alias call
            </>
        )
    },
    cannot_merge_attepts_exhausted: function Render(warning: IngestionWarning): JSX.Element {
        const details = warning.details as {
            sourcePersonDistinctId: string
            targetPersonDistinctId: string
            error: string
        }
        return (
            <>
                Merging <Link to={urls.person(details.sourcePersonDistinctId)}>{details.sourcePersonDistinctId}</Link>{' '}
                into <Link to={urls.person(details.targetPersonDistinctId)}>{details.targetPersonDistinctId}</Link> via
                an $identify or $create_alias call failed with error: {details.error}.
            </>
        )
    },
    skipping_event_invalid_uuid: function Render(warning: IngestionWarning): JSX.Element {
        const details = warning.details as {
            eventUuid: string
        }
        return <>Refused to process event with invalid uuid: {details.eventUuid}.</>
    },
}

export function IngestionWarningsView(): JSX.Element {
    const { data, dataLoading } = useValues(ingestionWarningsLogic)

    return (
        <div data-attr="manage-events-table">
            <PageHeader
                title="Data Management"
                caption="Use data management to organize events that come into PostHog. Reduce noise, clarify usage, and help collaborators get the most value from your data."
                tabbedPage
            />
            <DataManagementPageTabs tab={DataManagementTab.IngestionWarnings} />

            <div className="mb-4">Data ingestion related warnings from past 30 days.</div>

            <LemonTable
                dataSource={data}
                loading={dataLoading}
                columns={[
                    {
                        title: 'Warning',
                        dataIndex: 'type',
                        render: function Render(_, summary: IngestionWarningSummary) {
                            return <>{WARNING_TYPE_TO_DESCRIPTION[summary.type] || summary.type}</>
                        },
                    },
                    {
                        title: 'Graph',
                        render: function Render(_, summary: IngestionWarningSummary) {
                            return <WarningEventsGraph summary={summary} />
                        },
                    },
                    {
                        title: 'Events',
                        dataIndex: 'count',
                        align: 'right',
                        sorter: (a, b) => a.count - b.count,
                    },
                    {
                        title: 'Last Seen',
                        dataIndex: 'lastSeen',
                        render: function Render(_, summary: IngestionWarningSummary) {
                            return <TZLabel time={summary.lastSeen} showSeconds />
                        },
                        align: 'right',
                        sorter: (a, b) => (new Date(a.lastSeen) > new Date(b.lastSeen) ? 1 : -1),
                    },
                ]}
                expandable={{
                    expandedRowRender: RenderNestedWarnings,
                }}
                defaultSorting={{
                    columnKey: 'lastSeen',
                    order: -1,
                }}
                noSortingCancellation
            />
        </div>
    )
}

function RenderNestedWarnings(warningSummary: IngestionWarningSummary): JSX.Element {
    return (
        <LemonTable
            dataSource={warningSummary.warnings}
            columns={[
                {
                    title: 'Description',
                    key: 'description',
                    render: function Render(_, warning: IngestionWarning) {
                        const renderer = WARNING_TYPE_RENDERER[warning.type]
                        return renderer ? renderer(warning) : <pre>{JSON.stringify(warning.details, null, 2)}</pre>
                    },
                },
                {
                    title: 'Time',
                    dataIndex: 'timestamp',
                    render: function Render(_, warning: IngestionWarning) {
                        return <TZLabel time={warning.timestamp} showSeconds />
                    },
                    align: 'right',
                },
            ]}
            embedded
            size="small"
            showHeader={false}
        />
    )
}
