import { useActions, useValues } from 'kea'
import { EventType, RecordingWindowFilter, SessionRecordingPlayerTab } from '~/types'
import { PlayerList } from 'scenes/session-recordings/player/inspector/PlayerList'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { autoCaptureEventToDescription, capitalizeFirstLetter, interleave } from 'lib/utils'
import { RowStatus } from 'scenes/session-recordings/player/inspector/listLogic'
import { sharedListLogic, WindowOption } from 'scenes/session-recordings/player/inspector/sharedListLogic'
import { EventDetails } from 'scenes/events'
import React, { useMemo } from 'react'
import { LemonButton, LemonCheckbox, LemonDivider, LemonInput, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'
import { UnverifiedEvent, IconTerminal, IconInfo, IconGauge, IconSchedule, IconPlayCircle } from 'lib/components/icons'
import { SessionRecordingPlayerLogicProps } from '../sessionRecordingPlayerLogic'
import { Tooltip } from 'antd'
import { IconWindow } from '../icons'
import { consoleLogsListLogic } from './consoleLogsListLogic'
import { eventsListLogic } from './eventsListLogic'
import { playerMetaLogic } from '../playerMetaLogic'
import { PlayerInspectorList } from './v2/PlayerInspectorList'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { playerSettingsLogic } from '../playerSettingsLogic'

const TabToIcon = {
    [SessionRecordingPlayerTab.EVENTS]: <UnverifiedEvent />,
    [SessionRecordingPlayerTab.CONSOLE]: <IconTerminal />,
    [SessionRecordingPlayerTab.PERFORMANCE]: <IconGauge />,
}

export function PlayerInspector(props: SessionRecordingPlayerLogicProps): JSX.Element {
    const { sessionRecordingId, playerKey } = props
    const { tab } = useValues(sharedListLogic(props))
    const { featureFlags } = useValues(featureFlagLogic)
    const inspectorV2 = !!featureFlags[FEATURE_FLAGS.RECORDINGS_INSPECTOR_V2]

    return (
        <>
            <PlayerInspectorControls {...props} />
            <LemonDivider className="my-0" />

            {inspectorV2 ? (
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
    const { windowIdFilter, tab, searchQuery, miniFilters, timestampMode, syncScroll } = useValues(
        sharedListLogic(logicProps)
    )
    const { setWindowIdFilter, setTab, setSearchQuery, setTimestampMode, setMiniFilter, setSyncScroll } = useActions(
        sharedListLogic(logicProps)
    )
    const { showOnlyMatching } = useValues(playerSettingsLogic)
    const { setShowOnlyMatching } = useActions(playerSettingsLogic)
    const { eventListLocalFilters } = useValues(eventsListLogic(logicProps))
    const { setEventListLocalFilters } = useActions(eventsListLogic(logicProps))
    const { consoleListLocalFilters } = useValues(consoleLogsListLogic(logicProps))
    const { setConsoleListLocalFilters } = useActions(consoleLogsListLogic(logicProps))
    const { windowIds } = useValues(playerMetaLogic(logicProps))

    const { featureFlags } = useValues(featureFlagLogic)
    const inspectorV2 = !!featureFlags[FEATURE_FLAGS.RECORDINGS_INSPECTOR_V2]
    const inspectorPerformance = !!featureFlags[FEATURE_FLAGS.RECORDINGS_INSPECTOR_PERFORMANCE]

    const tabs = useMemo(() => {
        if (inspectorV2) {
            return [
                SessionRecordingPlayerTab.ALL,
                SessionRecordingPlayerTab.EVENTS,
                SessionRecordingPlayerTab.CONSOLE,
                inspectorPerformance ? SessionRecordingPlayerTab.PERFORMANCE : undefined,
            ].filter(Boolean) as SessionRecordingPlayerTab[]
        }
        return [SessionRecordingPlayerTab.EVENTS, SessionRecordingPlayerTab.CONSOLE]
    }, [inspectorV2, inspectorPerformance])

    return (
        <div className="bg-side p-2 space-y-2">
            <div className="flex justify-between gap-2 flex-wrap">
                <div className="flex flex-1 items-center gap-1">
                    {tabs.map((tabId) => (
                        <LemonButton
                            key={tabId}
                            size="small"
                            icon={TabToIcon[tabId]}
                            status={tab === tabId ? 'primary' : 'primary-alt'}
                            active={tab === tabId}
                            onClick={() => setTab(tabId)}
                        >
                            {capitalizeFirstLetter(tabId)}
                        </LemonButton>
                    ))}
                </div>

                {!inspectorV2 ? (
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
                ) : (
                    <div className="flex items-center gap-2 flex-1">
                        <LemonInput
                            className="min-w-40"
                            size="small"
                            onChange={(e) => setSearchQuery(e)}
                            placeholder="Search..."
                            type="search"
                            value={searchQuery}
                            fullWidth
                        />
                    </div>
                )}
                {windowIds.length > 1 ? (
                    <div className="flex items-center gap-2 flex-wrap">
                        <LemonSelect
                            size="small"
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
            {inspectorV2 ? (
                <>
                    <div className="flex items-center gap-2 justify-between">
                        <div className="flex items-center gap-1 flex-wrap font-medium text-primary-alt">
                            {miniFilters.map((filter) => (
                                <LemonButton
                                    key={filter.key}
                                    size="small"
                                    noPadding
                                    status="primary-alt"
                                    active={filter.enabled}
                                    onClick={() => {
                                        // "alone" should always be a select-to-true action
                                        setMiniFilter(filter.key, filter.alone || !filter.enabled)
                                    }}
                                >
                                    <span className="p-1 text-xs">{filter.name}</span>
                                </LemonButton>
                            ))}
                        </div>

                        <div className="flex items-center gap-1">
                            <LemonButton
                                size="small"
                                noPadding
                                status="primary-alt"
                                onClick={() => setTimestampMode(timestampMode === 'absolute' ? 'relative' : 'absolute')}
                                tooltipPlacement="left"
                                tooltip={
                                    timestampMode === 'absolute'
                                        ? 'Showing absolute timestamps'
                                        : 'Showing timestamps relative to the start of the recording'
                                }
                            >
                                <span className="p-1 flex items-center gap-1">
                                    <span className=" text-xs">{capitalizeFirstLetter(timestampMode)}</span>{' '}
                                    <IconSchedule className="text-lg" />
                                </span>
                            </LemonButton>

                            <LemonButton
                                size="small"
                                noPadding
                                status="primary-alt"
                                type={syncScroll ? 'primary' : 'tertiary'}
                                onClick={() => setSyncScroll(!syncScroll)}
                                tooltipPlacement="left"
                                tooltip={'Scroll the list in sync with the recording playback'}
                            >
                                <IconPlayCircle className="text-lg m-1" />
                            </LemonButton>
                        </div>
                    </div>
                    {matching?.length && tab === SessionRecordingPlayerTab.EVENTS ? (
                        <div className="flex items-center">
                            <span className="flex items-center whitespace-nowrap text-xs gap-1">
                                Only events matching filters
                                <Tooltip
                                    title="Display only the events that match the global filter."
                                    className="text-base text-muted-alt"
                                >
                                    <IconInfo />
                                </Tooltip>
                            </span>

                            <LemonCheckbox
                                className="mx-2"
                                checked={showOnlyMatching}
                                size="small"
                                onChange={setShowOnlyMatching}
                            />
                        </div>
                    ) : null}
                </>
            ) : null}
        </div>
    )
}
