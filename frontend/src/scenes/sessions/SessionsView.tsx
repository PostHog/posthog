import React, { useEffect, useRef } from 'react'
import { useValues, useActions, BindLogic } from 'kea'
import { decodeParams } from 'kea-router'
import { Button, Spin, Space, Badge, Switch, Row } from 'antd'
import { Link } from 'lib/components/Link'
import { ExpandState, sessionsTableLogic } from 'scenes/sessions/sessionsTableLogic'
import { humanFriendlyDetailedTime, stripHTTP, pluralize, colonDelimitedDuration } from '~/lib/utils'
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
    InfoCircleOutlined,
} from '@ant-design/icons'
import { SessionsPlayerButton, sessionPlayerUrl } from './SessionsPlayerButton'
import { SessionsPlay } from './SessionsPlay'
import { commandPaletteLogic } from 'lib/components/CommandPalette/commandPaletteLogic'
import { LinkButton } from 'lib/components/LinkButton'
import { SessionsFilterBox } from 'scenes/sessions/filters/SessionsFilterBox'
import { EditFiltersPanel } from 'scenes/sessions/filters/EditFiltersPanel'
import { SearchAllBox } from 'scenes/sessions/filters/SearchAllBox'
import { Drawer } from 'lib/components/Drawer'
import { Tooltip } from 'lib/components/Tooltip'

import dayjsGenerateConfig from 'rc-picker/lib/generate/dayjs'
import generatePicker from 'antd/es/date-picker/generatePicker'
import { ResizableTable, ResizableColumnType, ANTD_EXPAND_BUTTON_WIDTH } from 'lib/components/ResizableTable'
import { teamLogic } from 'scenes/teamLogic'
import { IconEventsShort } from 'lib/components/icons'
import { ExpandIcon } from 'lib/components/ExpandIcon'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

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

function getSessionRecordingsDurationSum(session: SessionType): number {
    return session.session_recordings.map(({ recording_duration }) => recording_duration).reduce((a, b) => a + b, 0)
}

export const MATCHING_EVENT_ICON_SIZE = 26

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
        expandedRowKeysProps,
        showOnlyMatches,
        filters,
        rowExpandState,
    } = useValues(logic)
    const {
        fetchNextSessions,
        previousDay,
        nextDay,
        setFilters,
        applyFilters,
        toggleExpandSessionRows,
        onExpandedRowsChange,
        setShowOnlyMatches,
    } = useActions(logic)
    const { currentTeam } = useValues(teamLogic)
    const { shareFeedbackCommand } = useActions(commandPaletteLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const sessionsTableRef = useRef<HTMLInputElement>(null)

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
            title: (
                <span>
                    Session Duration
                    <Tooltip title="Session duration is formatted as HH:MM:SS.">
                        <InfoCircleOutlined className="info-indicator" />
                    </Tooltip>
                </span>
            ),
            render: function RenderDuration(session: SessionType) {
                if (session.session_recordings.length > 0) {
                    const seconds = getSessionRecordingsDurationSum(session)
                    return <span>{colonDelimitedDuration(Math.max(seconds, session.length))}</span>
                }
                return <span>{colonDelimitedDuration(session.length)}</span>
            },
            span: 3,
        },
        {
            title: 'Start Time',
            render: function RenderStartTime(session: SessionType) {
                return <span>{humanFriendlyDetailedTime(session.start_time)}</span>
            },
            span: 3,
        },
        {
            title: 'Start Point',
            render: function RenderStartPoint(session: SessionType) {
                return <span>{session.start_url ? stripHTTP(session.start_url) : 'N/A'}</span>
            },
            ellipsis: true,
            span: 4,
        },
        {
            title: 'End Point',
            render: function RenderEndPoint(session: SessionType) {
                return <span>{session.end_url ? stripHTTP(session.end_url) : 'N/A'}</span>
            },
            ellipsis: true,
            span: 4,
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

    useEffect(() => {
        // scroll to sessions table if filters are defined in url from the get go
        if (decodeParams(window.location.hash)?.['#backTo'] === 'Insights' && sessionsTableRef.current) {
            sessionsTableRef.current.scrollIntoView({ behavior: 'smooth' })
        }
    }, [])

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

            <SearchAllBox />
            <SessionsFilterBox selector="new" />

            <BindLogic logic={sessionsTableLogic} props={{ personIds }}>
                <EditFiltersPanel onSubmit={applyFilters} />
            </BindLogic>

            {/* scroll to */}
            <div ref={sessionsTableRef} />

            <div className="sessions-view-actions">
                <div className="sessions-view-actions-left-items">
                    <Row className="action">
                        {featureFlags[FEATURE_FLAGS.SESSIONS_TABLE] && (
                            <Button data-attr="sessions-expand-collapse" onClick={toggleExpandSessionRows}>
                                {rowExpandState === ExpandState.Expanded ? 'Collapse' : 'Expand'} all
                            </Button>
                        )}
                    </Row>
                    {filters.length > 0 && (
                        <Row className="action ml-05">
                            <Switch
                                // @ts-expect-error `id` prop is valid on switch
                                id="show-only-matches"
                                onChange={setShowOnlyMatches}
                                checked={showOnlyMatches}
                            />
                            <label className="ml-025" htmlFor="show-only-matches">
                                <b>Show only event matches</b>
                            </label>
                        </Row>
                    )}
                </div>
                <div className="sessions-view-actions-right-items">
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
            </div>
            <ResizableTable
                locale={{
                    emptyText: selectedDate
                        ? `No Sessions on ${selectedDate.format(
                              selectedDate.year() == dayjs().year() ? 'MMM D' : 'MMM D, YYYY'
                          )}`
                        : 'No Sessions',
                }}
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
                        return (
                            <BindLogic logic={sessionsTableLogic} props={{ personIds }}>
                                <SessionDetails key={session.global_session_id} session={session} />
                            </BindLogic>
                        )
                    },
                    expandIcon: function _renderExpandIcon(expandProps) {
                        const { record: session } = expandProps
                        return (
                            <ExpandIcon {...expandProps}>
                                {session?.matching_events?.length > 0 ? (
                                    <Tooltip
                                        title={`${pluralize(session.matching_events.length, 'event')} ${pluralize(
                                            session.matching_events.length,
                                            'matches',
                                            'match',
                                            false
                                        )} your event filters`}
                                    >
                                        <Badge
                                            className="sessions-matching-events-icon cursor-pointer"
                                            count={<span className="badge-text">{session.matching_events.length}</span>}
                                            offset={[0, MATCHING_EVENT_ICON_SIZE]}
                                            size="small"
                                        >
                                            <IconEventsShort size={MATCHING_EVENT_ICON_SIZE} />
                                        </Badge>
                                    </Tooltip>
                                ) : (
                                    <></>
                                )}
                            </ExpandIcon>
                        )
                    },
                    columnWidth: ANTD_EXPAND_BUTTON_WIDTH + MATCHING_EVENT_ICON_SIZE,
                    rowExpandable: () => true,
                    onExpandedRowsChange: onExpandedRowsChange,
                    expandRowByClick: true,
                    ...expandedRowKeysProps,
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
