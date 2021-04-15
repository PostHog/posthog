import React from 'react'
import { useValues, useActions } from 'kea'
import { Button, Spin, Space, Tooltip } from 'antd'
import { Link } from 'lib/components/Link'
import { sessionsTableLogic } from 'scenes/sessions/sessionsTableLogic'
import { humanFriendlyDuration, humanFriendlyDetailedTime, stripHTTP } from '~/lib/utils'
import { SessionDetails } from './SessionDetails'
import dayjs from 'dayjs'
import { SessionType } from '~/types'
import {
    CaretLeftOutlined,
    CaretRightOutlined,
    PoweroffOutlined,
    QuestionCircleOutlined,
    ArrowLeftOutlined,
    PlaySquareOutlined,
} from '@ant-design/icons'
import { SessionsPlayerButton, sessionPlayerUrl } from './SessionsPlayerButton'
import { PropertyFilters } from 'lib/components/PropertyFilters'
import { SessionsPlay } from './SessionsPlay'
import { commandPaletteLogic } from 'lib/components/CommandPalette/commandPaletteLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { LinkButton } from 'lib/components/LinkButton'
import { SessionsFilterBox } from 'scenes/sessions/filters/SessionsFilterBox'
import { EditFiltersPanel } from 'scenes/sessions/filters/EditFiltersPanel'
import { SearchAllBox } from 'scenes/sessions/filters/SearchAllBox'
import { Drawer } from 'lib/components/Drawer'

import dayjsGenerateConfig from 'rc-picker/lib/generate/dayjs'
import generatePicker from 'antd/es/date-picker/generatePicker'
import { ResizableTable, ResizableColumnType } from 'lib/components/ResizableTable'
import { teamLogic } from 'scenes/teamLogic'

const DatePicker = generatePicker<dayjs.Dayjs>(dayjsGenerateConfig)

interface SessionsTableProps {
    personIds?: string[]
    isPersonPage?: boolean
}

function SessionPlayerDrawer({ isPersonPage = false }: { isPersonPage: boolean }): JSX.Element {
    const { closeSessionPlayer } = useActions(sessionsTableLogic)
    return (
        <Drawer destroyOnClose visible width="100%" onClose={closeSessionPlayer}>
            <>
                <a onClick={closeSessionPlayer}>
                    <ArrowLeftOutlined /> Back to {isPersonPage ? 'persons' : 'sessions'}
                </a>
                <SessionsPlay />
            </>
        </Drawer>
    )
}

export function SessionsView({ personIds, isPersonPage = false }: SessionsTableProps): JSX.Element {
    const logic = sessionsTableLogic({ personIds })
    const {
        sessions,
        sessionsLoading,
        pagination,
        isLoadingNext,
        selectedDate,
        properties,
        sessionRecordingId,
        firstRecordingId,
    } = useValues(logic)
    const { fetchNextSessions, previousDay, nextDay, setFilters, applyFilters } = useActions(logic)
    const { currentTeam } = useValues(teamLogic)
    const { shareFeedbackCommand } = useActions(commandPaletteLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const enableSessionRecordingCTA = (
        <>
            Session recording is turned off for this project. Go to{' '}
            <Link to="/project/settings#session-recording"> project settings</Link> to enable.
        </>
    )

    const playAllCTA =
        firstRecordingId === null
            ? currentTeam?.session_recording_opt_in
                ? 'No recordings found for this date'
                : enableSessionRecordingCTA
            : undefined

    const columns: ResizableColumnType<SessionType>[] = [
        {
            title: 'Person',
            key: 'person',
            render: function RenderSession(session: SessionType) {
                return (
                    <Link to={`/person/${encodeURIComponent(session.distinct_id)}`} className="ph-no-capture">
                        {session?.email || session.distinct_id}
                    </Link>
                )
            },
            ellipsis: true,
            span: 3,
        },
        {
            title: 'Event Count',
            render: function RenderDuration(session: SessionType) {
                return <span>{session.event_count}</span>
            },
            span: 1.5,
        },
        {
            title: 'Session duration',
            render: function RenderDuration(session: SessionType) {
                return <span>{humanFriendlyDuration(session.length)}</span>
            },
            span: 1.5,
        },
        {
            title: 'Start Time',
            render: function RenderStartTime(session: SessionType) {
                return <span>{humanFriendlyDetailedTime(session.start_time)}</span>
            },
            span: 2.5,
        },
        {
            title: 'End Time',
            render: function RenderEndTime(session: SessionType) {
                return <span>{humanFriendlyDetailedTime(session.end_time)}</span>
            },
            span: 2.5,
        },
        {
            title: 'Start Point',
            render: function RenderStartPoint(session: SessionType) {
                const url = session.start_url || (session.events && session.events[0].properties?.$current_url)
                return <span>{url ? stripHTTP(url) : 'N/A'}</span>
            },
            ellipsis: true,
            span: 3,
        },
        {
            title: 'End Point',
            render: function RenderEndPoint(session: SessionType) {
                const url =
                    session.end_url ||
                    (session.events && session.events[session.events.length - 1].properties?.$current_url)
                return <span>{url ? stripHTTP(url) : 'N/A'}</span>
            },
            ellipsis: true,
            span: 3,
        },
        {
            title: (
                <span>
                    {currentTeam?.session_recording_opt_in ? (
                        <Tooltip
                            title={
                                <>
                                    Replay sessions as if you were in front of your users. Not seeing a recording you're
                                    expecting? <a onClick={() => shareFeedbackCommand()}>Let us know</a>.
                                </>
                            }
                        >
                            <span>
                                Play recording
                                <QuestionCircleOutlined style={{ marginLeft: 6 }} />
                            </span>
                        </Tooltip>
                    ) : (
                        <Tooltip title={enableSessionRecordingCTA}>
                            <span>
                                <PoweroffOutlined style={{ marginRight: 6 }} className="text-warning" />
                                Play recording
                            </span>
                        </Tooltip>
                    )}
                </span>
            ),
            render: function RenderEndPoint(session: SessionType) {
                return <SessionsPlayerButton session={session} />
            },
            ellipsis: true,
            span: 2.5,
        },
    ]

    return (
        <div className="events" data-attr="events-table">
            <Space className="mb-05">
                <Button onClick={previousDay} icon={<CaretLeftOutlined />} data-attr="sessions-prev-date" />
                <DatePicker
                    value={selectedDate}
                    onChange={(date) => setFilters(properties, date)}
                    allowClear={false}
                    data-attr="sessions-date-picker"
                />
                <Button onClick={nextDay} icon={<CaretRightOutlined />} data-attr="sessions-next-date" />
            </Space>

            {featureFlags['filter_by_session_props'] && (
                <>
                    <SearchAllBox />
                    <SessionsFilterBox selector="new" />
                </>
            )}

            {featureFlags['filter_by_session_props'] ? (
                <EditFiltersPanel onSubmit={applyFilters} />
            ) : (
                <PropertyFilters pageKey={'sessions-' + (personIds && JSON.stringify(personIds))} endpoint="sessions" />
            )}

            <div className="text-right mb mt">
                <Tooltip title={playAllCTA}>
                    <span>
                        <LinkButton
                            to={firstRecordingId ? sessionPlayerUrl(firstRecordingId) : '#'}
                            type="primary"
                            data-attr="play-all-recordings"
                            disabled={firstRecordingId === null} // We allow playback of previously recorded sessions even if new recordings are disabled
                        >
                            <PlaySquareOutlined /> Play all
                        </LinkButton>
                    </span>
                </Tooltip>
            </div>

            <ResizableTable
                locale={{ emptyText: 'No Sessions on ' + dayjs(selectedDate).format('YYYY-MM-DD') }}
                data-attr="sessions-table"
                size="small"
                rowKey="global_session_id"
                pagination={{ pageSize: 99999, hideOnSinglePage: true }}
                rowClassName="cursor-pointer"
                dataSource={sessions}
                columns={columns}
                loading={sessionsLoading}
                expandable={{
                    expandedRowRender: function renderExpand(session) {
                        return <SessionDetails key={session.global_session_id} session={session} />
                    },
                    rowExpandable: () => true,
                    expandRowByClick: true,
                }}
            />
            {!!sessionRecordingId && <SessionPlayerDrawer isPersonPage={isPersonPage} />}
            <div style={{ marginTop: '5rem' }} />
            <div
                style={{
                    margin: '2rem auto 5rem',
                    textAlign: 'center',
                }}
            >
                {(pagination || isLoadingNext) && (
                    <Button type="primary" onClick={fetchNextSessions} data-attr="load-more-sessions">
                        {isLoadingNext ? <Spin> </Spin> : 'Load more sessions'}
                    </Button>
                )}
            </div>
        </div>
    )
}
