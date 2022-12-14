import { useActions, useValues } from 'kea'
import { EventType, RecordingWindowFilter, SessionRecordingPlayerTab } from '~/types'
import { PlayerList } from 'scenes/session-recordings/player/inspector/PlayerList'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { autoCaptureEventToDescription, capitalizeFirstLetter, interleave } from 'lib/utils'
import { RowStatus } from 'scenes/session-recordings/player/inspector/listLogic'
import { sharedListLogic, WindowOption } from 'scenes/session-recordings/player/inspector/sharedListLogic'
import { EventDetails } from 'scenes/events'
import React from 'react'
import { LemonButton, LemonDivider, LemonInput, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'
import { UnverifiedEvent, IconTerminal, IconInfo, IconGauge } from 'lib/components/icons'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { SessionRecordingPlayerLogicProps } from '../sessionRecordingPlayerLogic'
import { Tooltip } from 'antd'
import { IconWindow } from '../icons'
import { consoleLogsListLogic } from './consoleLogsListLogic'
import { eventsListLogic } from './eventsListLogic'
import { playerMetaLogic } from '../playerMetaLogic'
import { PlayerInspectorList } from './v2/PlayerInspectorList'

const TabToIcon = {
    [SessionRecordingPlayerTab.EVENTS]: <UnverifiedEvent />,
    [SessionRecordingPlayerTab.CONSOLE]: <IconTerminal />,
    [SessionRecordingPlayerTab.PERFORMANCE]: <IconGauge />,
}

export function PlayerInspector(props: SessionRecordingPlayerLogicProps): JSX.Element {
    const { sessionRecordingId, playerKey } = props
    const { tab } = useValues(sharedListLogic(props))

    return (
        <>
            <PlayerInspectorControls {...props} />
            <LemonDivider className="my-0" />

            {tab === SessionRecordingPlayerTab.PERFORMANCE ? (
                <PlayerInspectorList {...props} />
            ) : (
                <PlayerList
                    sessionRecordingId={sessionRecordingId}
                    playerKey={playerKey}
                    tab={tab}
                    row={{
                        status: (record) => {
                            if (record.level === 'match') {
                                return RowStatus.Match
                            }
                            if (tab === SessionRecordingPlayerTab.EVENTS) {
                                return null
                            }
                            // Below statuses only apply to console logs
                            if (record.level === 'warn') {
                                return RowStatus.Warning
                            }
                            if (record.level === 'log') {
                                return RowStatus.Information
                            }
                            if (record.level === 'error') {
                                return RowStatus.Error
                            }
                            if (record.level === 'error') {
                                return RowStatus.Error
                            }
                            return RowStatus.Information
                        },
                        content: function renderContent(record, _, expanded) {
                            if (tab === SessionRecordingPlayerTab.CONSOLE) {
                                return (
                                    <div
                                        className="font-mono text-xs w-full text-ellipsis leading-6"
                                        // eslint-disable-next-line react/forbid-dom-props
                                        style={
                                            expanded
                                                ? {
                                                      display: '-webkit-box',
                                                      WebkitLineClamp: 6,
                                                      WebkitBoxOrient: 'vertical',
                                                      overflow: 'hidden',
                                                      whiteSpace: 'normal',
                                                  }
                                                : undefined
                                        }
                                    >
                                        {interleave(record.previewContent, ' ')}
                                    </div>
                                )
                            }

                            return (
                                <div className="flex flex-row justify-start whitespace-nowrap">
                                    <PropertyKeyInfo
                                        className="font-medium"
                                        disableIcon
                                        disablePopover
                                        ellipsis={true}
                                        value={capitalizeFirstLetter(autoCaptureEventToDescription(record as any))}
                                    />
                                    {record.event === '$autocapture' ? (
                                        <span className="text-muted-alt ml-2">(Autocapture)</span>
                                    ) : null}
                                    {record.event === '$pageview' ? (
                                        <span className="text-muted-alt ml-2">
                                            {record.properties.$pathname || record.properties.$current_url}
                                        </span>
                                    ) : null}
                                </div>
                            )
                        },
                        sideContent: function renderSideContent(record) {
                            if (tab === SessionRecordingPlayerTab.CONSOLE) {
                                return <div className="font-mono text-xs">{record.traceContent?.[0]}</div>
                            }
                            return null
                        },
                    }}
                    expandable={{
                        expandedRowRender: function renderExpand(record) {
                            if (!record) {
                                return null
                            }
                            if (tab === SessionRecordingPlayerTab.CONSOLE) {
                                return (
                                    <div className="py-2 pr-2 pl-18 font-mono text-xs leading-6">
                                        {record.fullContent?.map((content: JSX.Element, i: number) => (
                                            <React.Fragment key={i}>
                                                {content}
                                                <br />
                                            </React.Fragment>
                                        ))}
                                    </div>
                                )
                            }
                            return (
                                <EventDetails
                                    event={record as EventType}
                                    tableProps={{ size: 'xs', bordered: false, className: 'pt-1' }}
                                />
                            )
                        },
                    }}
                />
            )}
        </>
    )
}

export function PlayerInspectorControls({
    sessionRecordingId,
    playerKey,
    matching,
}: SessionRecordingPlayerLogicProps): JSX.Element {
    const logicProps = { sessionRecordingId, playerKey }
    const { windowIdFilter, showOnlyMatching, tab, searchQuery } = useValues(sharedListLogic(logicProps))
    const { setWindowIdFilter, setShowOnlyMatching, setTab, setSearchQuery } = useActions(sharedListLogic(logicProps))
    const { eventListLocalFilters } = useValues(eventsListLogic(logicProps))
    const { setEventListLocalFilters } = useActions(eventsListLogic(logicProps))
    const { consoleListLocalFilters } = useValues(consoleLogsListLogic(logicProps))
    const { setConsoleListLocalFilters } = useActions(consoleLogsListLogic(logicProps))
    const { windowIds } = useValues(playerMetaLogic(logicProps))

    const { ref, size } = useResizeBreakpoints({
        0: 'compact',
        200: 'normal',
    })

    return (
        <div className="bg-side">
            <div ref={ref} className="flex justify-between gap-2 p-2 flex-wrap">
                <div className="flex flex-1 items-center gap-1">
                    {[
                        SessionRecordingPlayerTab.EVENTS,
                        SessionRecordingPlayerTab.CONSOLE,
                        SessionRecordingPlayerTab.PERFORMANCE,
                    ].map((tabId) => (
                        <LemonButton
                            key={tabId}
                            size="small"
                            icon={TabToIcon[tabId]}
                            status={tab === tabId ? 'primary' : 'primary-alt'}
                            active={tab === tabId}
                            onClick={() => setTab(tabId)}
                        >
                            {size === 'compact' ? '' : capitalizeFirstLetter(tabId)}
                        </LemonButton>
                    ))}
                </div>

                <div className="flex items-center gap-2 flex-wrap">
                    {tab === SessionRecordingPlayerTab.EVENTS ? (
                        <>
                            <LemonInput
                                key="event-list-search-input"
                                onChange={(query) => setEventListLocalFilters({ query })}
                                placeholder="Search events"
                                type="search"
                                value={eventListLocalFilters.query}
                            />
                            {matching?.length ? (
                                <LemonSwitch
                                    checked={showOnlyMatching}
                                    bordered
                                    label={
                                        <span className="flex items-center gap-2 whitespace-nowrap">
                                            Only show matching events
                                            <Tooltip
                                                title="Display only the events that match the global filter."
                                                className="text-base text-muted-alt mr-2"
                                            >
                                                <IconInfo />
                                            </Tooltip>
                                        </span>
                                    }
                                    onChange={setShowOnlyMatching}
                                />
                            ) : null}
                        </>
                    ) : tab === SessionRecordingPlayerTab.CONSOLE ? (
                        <LemonInput
                            key="console-list-search-input"
                            onChange={(query) => setConsoleListLocalFilters({ query })}
                            placeholder="Search console logs"
                            type="search"
                            value={consoleListLocalFilters.query}
                        />
                    ) : null}
                </div>

                {windowIds.length > 1 ? (
                    <div className="flex items-center gap-2 flex-wrap">
                        <LemonSelect
                            data-attr="player-window-select"
                            value={windowIdFilter ?? undefined}
                            onChange={(val) => setWindowIdFilter(val as WindowOption)}
                            options={[
                                {
                                    value: RecordingWindowFilter.All,
                                    label: 'All windows',
                                    icon: <IconWindow value="A" className="text-muted" />,
                                },
                                ...windowIds.map((windowId, index) => ({
                                    value: windowId,
                                    label: `Window ${index + 1}`,
                                    icon: <IconWindow value={index + 1} className="text-muted" />,
                                })),
                            ]}
                        />
                        <Tooltip
                            title="Each recording window translates to a distinct browser tab or window."
                            className="text-base text-muted-alt mr-2"
                        >
                            <IconInfo />
                        </Tooltip>
                    </div>
                ) : null}
            </div>
            {tab === SessionRecordingPlayerTab.PERFORMANCE ? (
                <>
                    <div className="flex items-center gap-2 px-2">
                        <LemonInput
                            size="small"
                            onChange={(e) => setSearchQuery(e)}
                            placeholder="Search..."
                            type="search"
                            value={searchQuery}
                            fullWidth
                        />
                    </div>

                    <div className="flex items-center gap-1 flex-wrap px-2 text-xs my-2 font-medium">
                        <span className="cursor-pointer p-1 px-1 rounded bg-primary-alt-highlight">All</span>
                        <span className="cursor-pointer p-1 px-1 rounded text-muted">Page</span>
                        <span className="cursor-pointer p-1 px-1 rounded text-muted">XHR / Fetch</span>
                        <span className="cursor-pointer p-1 px-1 rounded text-muted">Assets</span>
                        <span className="cursor-pointer p-1 px-1 rounded text-muted">Other</span>
                    </div>
                </>
            ) : null}
        </div>
    )
}
