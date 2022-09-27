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

export const scene: SceneExport = {
    component: IngestionWarningsView,
    logic: ingestionWarningsLogic,
}

const WARNING_TYPE_TO_DESCRIPTION = {
    cannot_merge_already_identified: 'Refused to merge an already identified user via $identify or $create_alias call',
}

const WARNING_TYPE_RENDERER = {
    cannot_merge_already_identified: function Render(warning: IngestionWarning): JSX.Element {
        const details = warning.details as {
            sourcePerson: string
            sourcePersonDistinctId: string
            targetPerson: string
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
                        title: 'Events',
                        dataIndex: 'count',
                        align: 'right',
                    },
                    {
                        title: 'Last Seen',
                        dataIndex: 'lastSeen',
                        render: function Render(_, summary: IngestionWarningSummary) {
                            return <TZLabel time={summary.lastSeen} showSeconds />
                        },
                        align: 'right',
                    },
                ]}
                expandable={{
                    expandedRowRender: RenderNestedWarnings,
                }}
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
