import React from 'react'
import { useValues, useActions } from 'kea'
import { Table, Button, Spin, Space, Tooltip, Drawer } from 'antd'
import { Link } from 'lib/components/Link'
import { sessionsTableLogic } from 'scenes/sessions/sessionsTableLogic'
import { humanFriendlyDuration, humanFriendlyDetailedTime, stripHTTP } from '~/lib/utils'
import { SessionDetails } from './SessionDetails'
import { DatePicker } from 'antd'
import moment from 'moment'
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
import rrwebBlockClass from 'lib/utils/rrwebBlockClass'
import { SessionsPlay } from './SessionsPlay'
import { userLogic } from 'scenes/userLogic'
import { commandPaletteLogic } from 'lib/components/CommandPalette/commandPaletteLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { LinkButton } from 'lib/components/LinkButton'
import { SessionsFilterBox } from 'scenes/sessions/filters/SessionsFilterBox'
import { EditFiltersPanel } from 'scenes/sessions/filters/EditFiltersPanel'
import { SearchAllBox } from 'scenes/sessions/filters/SearchAllBox'

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
    const { user } = useValues(userLogic)
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
            ? user?.team?.session_recording_opt_in
                ? 'No recordings found for this date'
                : enableSessionRecordingCTA
            : undefined

    const columns = [
        {
            title: 'Person',
            key: 'person',
            render: function RenderSession(session: SessionType) {
                return (
                    <Link
                        to={`/person/${encodeURIComponent(session.distinct_id)}`}
                        className={rrwebBlockClass + ' ph-no-capture'}
                    >
                        {session?.email || session.distinct_id}
                    </Link>
                )
            },
            ellipsis: true,
        },
        {
            title: 'Event Count',
            render: function RenderDuration(session: SessionType) {
                return <span>{session.event_count}</span>
            },
        },
        {
            title: 'Session duration',
            render: function RenderDuration(session: SessionType) {
                return <span>{humanFriendlyDuration(session.length)}</span>
            },
        },
        {
            title: 'Start Time',
            render: function RenderStartTime(session: SessionType) {
                return <span>{humanFriendlyDetailedTime(session.start_time)}</span>
            },
        },
        {
            title: 'End Time',
            render: function RenderEndTime(session: SessionType) {
                return <span>{humanFriendlyDetailedTime(session.end_time)}</span>
            },
        },
        {
            title: 'Start Point',
            render: function RenderStartPoint(session: SessionType) {
                const url = session.start_url || (session.events && session.events[0].properties?.$current_url)
                return <span>{url ? stripHTTP(url) : 'N/A'}</span>
            },
            ellipsis: true,
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
        },
        {
            title: (
                <span>
                    {user?.team?.session_recording_opt_in ? (
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
        },
    ]

    return (
        <div className="events" data-attr="events-table">
            <Space className="mb-05">
                <Button onClick={previousDay} icon={<CaretLeftOutlined />} />
                <DatePicker value={selectedDate} onChange={(date) => setFilters(properties, date)} allowClear={false} />
                <Button onClick={nextDay} icon={<CaretRightOutlined />} />
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
                            icon={<PlaySquareOutlined />}
                            type="primary"
                            data-attr="play-all-recordings"
                            disabled={firstRecordingId === null} // We allow playback of previously recorded sessions even if new recordings are disabled
                        >
                            Play all
                        </LinkButton>
                    </span>
                </Tooltip>
            </div>

            <Table
                locale={{ emptyText: 'No Sessions on ' + moment(selectedDate).format('YYYY-MM-DD') }}
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
                    <Button type="primary" onClick={fetchNextSessions}>
                        {isLoadingNext ? <Spin> </Spin> : 'Load more sessions'}
                    </Button>
                )}
            </div>
        </div>
    )
}
