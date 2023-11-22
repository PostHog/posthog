import { useValues } from 'kea'
import { ReadingHog } from 'lib/components/hedgehogs'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { TableCellSparkline } from 'lib/lemon-ui/LemonTable/TableCellSparkline'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/types'

import { IngestionWarning, ingestionWarningsLogic, IngestionWarningSummary } from './ingestionWarningsLogic'

const WARNING_TYPE_TO_DESCRIPTION = {
    cannot_merge_already_identified: 'Refused to merge an already identified user',
    cannot_merge_with_illegal_distinct_id: 'Refused to merge with an illegal distinct id',
    skipping_event_invalid_uuid: 'Refused to process event with invalid uuid',
    ignored_invalid_timestamp: 'Ignored an invalid timestamp, event was still ingested',
    event_timestamp_in_future: 'An event was sent more than 23 hours in the future',
    ingestion_capacity_overflow: 'Event ingestion has overflowed capacity',
    message_size_too_large: 'Discarded event exceeding 1MB limit',
}

const WARNING_TYPE_RENDERER = {
    cannot_merge_already_identified: function Render(warning: IngestionWarning): JSX.Element {
        const details = warning.details as {
            sourcePersonDistinctId: string
            targetPersonDistinctId: string
            eventUuid: string
        }
        return (
            <>
                Refused to merge already identified person{' '}
                <Link to={urls.personByDistinctId(details.sourcePersonDistinctId)}>
                    {details.sourcePersonDistinctId}
                </Link>{' '}
                into{' '}
                <Link to={urls.personByDistinctId(details.targetPersonDistinctId)}>
                    {details.targetPersonDistinctId}
                </Link>{' '}
                via an $identify or $create_alias call (event uuid: <code>{details.eventUuid}</code>).
            </>
        )
    },
    cannot_merge_with_illegal_distinct_id: function Render(warning: IngestionWarning): JSX.Element {
        const details = warning.details as {
            illegalDistinctId: string
            otherDistinctId: string
            eventUuid: string
        }
        return (
            <>
                Refused to merge an illegal distinct_id{' '}
                <Link to={urls.personByDistinctId(details.illegalDistinctId)}>{details.illegalDistinctId}</Link> with{' '}
                <Link to={urls.personByDistinctId(details.otherDistinctId)}>{details.otherDistinctId}</Link> via an
                $identify or $create_alias call (event uuid: <code>{details.eventUuid}</code>).
            </>
        )
    },
    skipping_event_invalid_uuid: function Render(warning: IngestionWarning): JSX.Element {
        const details = warning.details as {
            eventUuid: string
        }
        return (
            <>
                Refused to process event with invalid uuid: <code>{details.eventUuid}</code>.
            </>
        )
    },
    ignored_invalid_timestamp: function Render(warning: IngestionWarning): JSX.Element {
        const details = warning.details as {
            eventUuid: string
            field: string
            value: string
            reason: string
        }
        return (
            <>
                Used server timestamp when ingesting event due to invalid input:
                <ul>
                    {details.eventUuid ? <li>Event UUID: {details.eventUuid}</li> : ''}
                    {details.field ? <li>Invalid field: {details.field}</li> : ''}
                    {details.value ? <li>Invalid value: {details.value}</li> : ''}
                    {details.reason ? <li>Error: {details.reason}</li> : ''}
                </ul>
            </>
        )
    },
    event_timestamp_in_future: function Render(warning: IngestionWarning): JSX.Element {
        const details = warning.details as {
            eventUuid: string
            timestamp: string
            sentAt: string
            offset: string
            now: string
            result: string
        }
        return (
            <>
                The event timestamp computed too far in the future, so the capture time was used instead. Event values:
                <ul>
                    <li>Computed timestamp: {details.result}</li>
                    {details.eventUuid ? <li>Event UUID: {details.eventUuid}</li> : ''}
                    {details.timestamp ? <li>Client provided timestamp: {details.timestamp}</li> : ''}
                    {details.sentAt ? <li>Client provided sent_at: {details.sentAt}</li> : ''}
                    {details.offset ? <li>Client provided time offset: {details.offset}</li> : ''}
                    <li>PostHog server capture time: {details.now}</li>
                </ul>
            </>
        )
    },
    ingestion_capacity_overflow: function Render(warning: IngestionWarning): JSX.Element {
        const details = warning.details as {
            overflowDistinctId: string
        }
        return (
            <>
                Event ingestion has overflowed capacity for distinct_id{' '}
                <Link to={urls.personByDistinctId(details.overflowDistinctId)}>{details.overflowDistinctId}</Link>.
                Events will still be processed, but are likely to be delayed longer than usual.
            </>
        )
    },
    message_size_too_large: function Render(warning: IngestionWarning): JSX.Element {
        const details = warning.details as {
            eventUuid: string
            distinctId: string
        }
        return (
            <>
                Discarded event for distinct_id{' '}
                <Link to={urls.personByDistinctId(details.distinctId)}>{details.distinctId}</Link> that exceeded 1MB in
                size after processing (event uuid: <code>{details.eventUuid}</code>)
            </>
        )
    },
}

export function IngestionWarningsView(): JSX.Element {
    const { data, dataLoading, summaryDatasets, dates } = useValues(ingestionWarningsLogic)

    return (
        <div data-attr="manage-events-table">
            {data.length > 0 || dataLoading ? (
                <>
                    <div className="mb-4">Data ingestion related warnings from past 30 days.</div>
                    <LemonTable
                        dataSource={data}
                        loading={dataLoading}
                        columns={[
                            {
                                title: 'Warning',
                                dataIndex: 'type',
                                render: function Render(_, summary: IngestionWarningSummary) {
                                    const type = WARNING_TYPE_TO_DESCRIPTION[summary.type] || summary.type
                                    return (
                                        <>
                                            {type} (
                                            <Link
                                                to={`https://posthog.com/manual/data-management#${type
                                                    .toLowerCase()
                                                    .replace(',', '')
                                                    .split(' ')
                                                    .join('-')}`}
                                            >
                                                {'docs'})
                                            </Link>
                                        </>
                                    )
                                },
                            },
                            {
                                title: 'Graph',
                                render: function Render(_, summary: IngestionWarningSummary) {
                                    return <TableCellSparkline labels={dates} data={summaryDatasets[summary.type]} />
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
                </>
            ) : (
                <ProductIntroduction
                    productName="Ingestion warnings"
                    thingName="ingestion warning"
                    productKey={ProductKey.INGESTION_WARNINGS}
                    isEmpty={true}
                    description="Nice! You've had no ingestion warnings in the past 30 days. If we detect any issues with your data, we'll show them here."
                    docsURL="https://posthog.com/docs/data/data-management#ingestion-warnings"
                    customHog={ReadingHog}
                />
            )}
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
