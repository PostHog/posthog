import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { Sparkline } from 'lib/components/Sparkline'
import { TZLabel } from 'lib/components/TZLabel'
import ViewRecordingButton from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { ReadingHog } from 'lib/components/hedgehogs'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { Link } from 'lib/lemon-ui/Link'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/types'

import { IngestionWarning, IngestionWarningSummary, ingestionWarningsLogic } from './ingestionWarningsLogic'

const WARNING_TYPE_TO_DESCRIPTION = {
    cannot_merge_already_identified: 'Refused to merge an already identified user',
    cannot_merge_with_illegal_distinct_id: 'Refused to merge with an illegal distinct id',
    skipping_event_invalid_uuid: 'Refused to process event with invalid uuid',
    ignored_invalid_timestamp: 'Ignored an invalid timestamp, event was still ingested',
    event_timestamp_in_future: 'An event was sent more than 23 hours in the future',
    ingestion_capacity_overflow: 'Event ingestion has overflowed capacity',
    message_size_too_large: 'Discarded event exceeding 1MB limit',
    replay_timestamp_invalid: 'Replay event timestamp is invalid',
    replay_timestamp_too_far: 'Replay event timestamp was too far in the future',
    replay_message_too_large: 'Replay data was dropped because it was too large to ingest',
    set_on_exception: '$set or $set_once is ignored on exception events and should not be sent',
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
    replay_timestamp_invalid: function Render(warning: IngestionWarning): JSX.Element {
        const details: {
            timestamp: string
            session_id: string
        } = {
            timestamp: warning.details.timestamp,
            session_id: warning.details.replayRecord.session_id,
        }
        return (
            <>
                Session replay data dropped due to invalid timestamp:
                <ul>
                    <li>invalid timestamp: {details.timestamp}</li>
                    <li>session_id: {details.session_id}</li>
                </ul>
                <div className="max-w-30 mt-2">
                    <ViewRecordingButton
                        sessionId={details.session_id}
                        timestamp={details.timestamp}
                        type="primary"
                        size="xsmall"
                        data-attr="skewed-timestamp-view-recording"
                    />
                </div>
            </>
        )
    },
    replay_timestamp_too_far: function Render(warning: IngestionWarning): JSX.Element {
        const details: {
            timestamp: string
            session_id: string
            daysFromNow: string
        } = {
            timestamp: warning.details.timestamp,
            session_id: warning.details.replayRecord.session_id,
            daysFromNow: warning.details.daysFromNow,
        }
        return (
            <>
                The session replay data timestamp was too different from the capture time, so the data was dropped.
                Event values:
                <ul>
                    <li>invalid timestamp: {details.timestamp}</li>
                    <li>session_id: {details.session_id}</li>
                    <li>skew: {details.daysFromNow} days</li>
                </ul>
                <div className="max-w-30 mt-2">
                    <ViewRecordingButton
                        sessionId={details.session_id}
                        timestamp={details.timestamp}
                        type="primary"
                        size="xsmall"
                        data-attr="skewed-timestamp-view-recording"
                    />
                </div>
            </>
        )
    },
    replay_message_too_large: function Render(warning: IngestionWarning): JSX.Element {
        const details: {
            timestamp: string
            session_id: string
        } = {
            timestamp: warning.details.timestamp,
            session_id: warning.details.replayRecord.session_id,
        }
        return (
            <>
                Session replay data dropped due to its size, this can cause playback problems:
                <ul>
                    <li>session_id: {details.session_id}</li>
                </ul>
                <div className="max-w-30 mt-2">
                    <ViewRecordingButton
                        sessionId={details.session_id}
                        timestamp={details.timestamp}
                        type="primary"
                        size="xsmall"
                        data-attr="message-too-large-view-recording"
                    />
                </div>
            </>
        )
    },
    set_on_exception: function Render(warning: IngestionWarning): JSX.Element {
        const details: {
            event_uuid: string
        } = {
            event_uuid: warning.details.event_uuid,
        }

        return (
            <>
                {' '}
                Exception {details.event_uuid} contained $set or $set_once properties, which are ignored on exception
                events
            </>
        )
    },
}

export function IngestionWarningsView(): JSX.Element {
    const { data, dataLoading, summaryDatasets, dates, searchQuery, showProductIntro } =
        useValues(ingestionWarningsLogic)
    const { setSearchQuery } = useActions(ingestionWarningsLogic)

    return (
        <SceneContent data-attr="manage-events-table">
            <SceneTitleSection
                name={sceneConfigurations[Scene.IngestionWarnings].name}
                description={sceneConfigurations[Scene.IngestionWarnings].description}
                resourceType={{
                    type: sceneConfigurations[Scene.IngestionWarnings].iconType || 'default_icon_type',
                }}
            />
            <SceneDivider />
            <SceneSection>
                <LemonInput
                    fullWidth
                    value={searchQuery}
                    onChange={setSearchQuery}
                    type="search"
                    placeholder="Try pasting a person or session id or an ingestion warning type"
                />
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
                                            to={`https://posthog.com/docs/data#${type
                                                .toLowerCase()
                                                .replace(',', '')
                                                .split(' ')
                                                .join('-')}`}
                                        >
                                            docs)
                                        </Link>
                                    </>
                                )
                            },
                        },
                        {
                            title: 'Graph',
                            render: function Render(_, summary: IngestionWarningSummary) {
                                return <Sparkline className="h-8" labels={dates} data={summaryDatasets[summary.type]} />
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
            </SceneSection>
            {showProductIntro && (
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
        </SceneContent>
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
            showHeader={false}
            pagination={{
                // In production this list can be huge - we don't want to render all of them at once
                pageSize: 20,
            }}
        />
    )
}
