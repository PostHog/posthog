import './PlayerInspectorList.scss'

import { LemonButton, Link } from '@posthog/lemon-ui'
import { range } from 'd3'
import { useActions, useValues } from 'kea'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { useEffect, useMemo, useRef } from 'react'
import AutoSizer from 'react-virtualized/dist/es/AutoSizer'
import { CellMeasurer, CellMeasurerCache } from 'react-virtualized/dist/es/CellMeasurer'
import { List, ListRowRenderer } from 'react-virtualized/dist/es/List'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'
import { AvailableFeature, SessionRecordingPlayerTab } from '~/types'

import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { PlayerInspectorListItem } from './components/PlayerInspectorListItem'
import { playerInspectorLogic } from './playerInspectorLogic'

function isLocalhost(url: string | null | undefined): boolean {
    try {
        return !!url && ['localhost', '127.0.0.1'].includes(new URL(url).hostname)
    } catch (e) {
        // for e.g. mobile doesn't have a URL, so we can swallow this and move on
        return false
    }
}

function EmptyNetworkTab({
    captureNetworkLogOptIn,
    captureNetworkFeatureAvailable,
    recordingURL,
}: {
    captureNetworkLogOptIn: boolean
    captureNetworkFeatureAvailable: boolean
    recordingURL: string | null | undefined
}): JSX.Element {
    const { openSettingsPanel } = useActions(sidePanelSettingsLogic)
    return !captureNetworkFeatureAvailable ? (
        <div className="p-4">
            <PayGateMini
                feature={AvailableFeature.RECORDINGS_PERFORMANCE}
                className="py-8"
                docsLink="https://posthog.com/docs/user-guides/recordings"
            />
        </div>
    ) : !captureNetworkLogOptIn ? (
        <>
            <div className="flex flex-col items-center">
                <h4 className="text-xl font-medium">Performance events</h4>
                <p className="text-muted text-center">
                    Capture performance events like network requests during the browser recording to understand things
                    like response times, page load times, and more.
                </p>
                <LemonButton
                    type="primary"
                    onClick={() => openSettingsPanel({ sectionId: 'project-replay' })}
                    targetBlank
                >
                    Configure in settings
                </LemonButton>
            </div>
        </>
    ) : isLocalhost(recordingURL) ? (
        <>
            <div className="flex flex-col items-center">
                <h4 className="text-xl font-medium">Network recording</h4>
                <p className="text-muted text-center">
                    Network capture is not supported when replay is running on localhost.{' '}
                    <Link to="https://posthog.com/docs/session-replay/network-recording">Learn more in our docs </Link>.
                </p>
            </div>
        </>
    ) : (
        <>No results found in this recording.</>
    )
}

function EmptyConsoleTab({ captureConsoleLogOptIn }: { captureConsoleLogOptIn: boolean }): JSX.Element {
    const { openSettingsPanel } = useActions(sidePanelSettingsLogic)

    return captureConsoleLogOptIn ? (
        <>No results found in this recording.</>
    ) : (
        <>
            <div className="flex flex-col items-center">
                <h4 className="text-xl font-medium">Console logs</h4>
                <p className="text-muted text-center">
                    Capture all console logs during the browser recording to get technical information on what was
                    occurring.
                </p>
                <LemonButton
                    type="primary"
                    onClick={() => openSettingsPanel({ sectionId: 'project-replay' })}
                    targetBlank
                >
                    Configure in settings
                </LemonButton>
            </div>
        </>
    )
}

export function PlayerInspectorList(): JSX.Element {
    const { logicProps, snapshotsLoaded, sessionPlayerMetaData } = useValues(sessionRecordingPlayerLogic)
    const inspectorLogic = playerInspectorLogic(logicProps)

    const { items, tabsState, playbackIndicatorIndex, playbackIndicatorIndexStop, syncScrollPaused, tab } =
        useValues(inspectorLogic)
    const { setSyncScrollPaused } = useActions(inspectorLogic)
    const { currentTeam } = useValues(teamLogic)
    const { hasAvailableFeature } = useValues(userLogic)
    const performanceAvailable: boolean = hasAvailableFeature(AvailableFeature.RECORDINGS_PERFORMANCE)
    const performanceEnabled: boolean = currentTeam?.capture_performance_opt_in ?? false

    const cellMeasurerCache = useMemo(
        () =>
            new CellMeasurerCache({
                fixedWidth: true,
                minHeight: 10,
                defaultHeight: 40,
            }),
        []
    )

    const listRef = useRef<List | null>()
    const scrolledByJsFlag = useRef<boolean>(true)
    const mouseHoverRef = useRef<boolean>(false)

    // TRICKY: this is hacky but there is no other way to add a timestamp marker to the <List> component children
    // We want this as otherwise we would have a tonne of unnecessary re-rendering going on or poor scroll matching
    useEffect(() => {
        if (listRef.current) {
            if (document.getElementById('PlayerInspectorListMarker')) {
                return
            }
            const listElement = document.getElementById('PlayerInspectorList')
            const positionMarkerEl = document.createElement('div')
            positionMarkerEl.id = 'PlayerInspectorListMarker'
            listElement?.appendChild(positionMarkerEl)
        }
    }, [listRef.current])

    useEffect(() => {
        if (listRef.current) {
            const offset = range(playbackIndicatorIndexStop).reduce(
                (acc, x) => acc + cellMeasurerCache.getHeight(x, 0),
                0
            )
            document
                .getElementById('PlayerInspectorListMarker')
                ?.setAttribute('style', `transform: translateY(${offset}px)`)

            if (!syncScrollPaused) {
                scrolledByJsFlag.current = true
                listRef.current.scrollToRow(playbackIndicatorIndex)
            }
        }
    }, [playbackIndicatorIndex])

    const renderRow: ListRowRenderer = ({ index, key, parent, style }) => {
        return (
            <CellMeasurer cache={cellMeasurerCache} columnIndex={0} key={key} rowIndex={index} parent={parent}>
                {({ measure, registerChild }) => (
                    // eslint-disable-next-line react/forbid-dom-props
                    <div ref={(r) => registerChild?.(r || undefined)} style={style}>
                        <PlayerInspectorListItem
                            key={index}
                            item={items[index]}
                            index={index}
                            onLayout={({ height }) => {
                                // Optimization to ensure that we only call measure if the dimensions have actually changed
                                if (height !== cellMeasurerCache.getHeight(index, 0)) {
                                    measure()
                                }
                            }}
                        />
                    </div>
                )}
            </CellMeasurer>
        )
    }

    return (
        <div className="flex flex-col bg-bg-3000 flex-1 overflow-hidden relative">
            {!snapshotsLoaded ? (
                <div className="p-16 text-center text-muted-alt">Data will be shown once playback starts</div>
            ) : items.length ? (
                <div
                    className="absolute inset-0"
                    onMouseEnter={() => (mouseHoverRef.current = true)}
                    onMouseLeave={() => (mouseHoverRef.current = false)}
                >
                    <AutoSizer>
                        {({ height, width }) => (
                            <List
                                className="p-2"
                                height={height}
                                width={width}
                                deferredMeasurementCache={cellMeasurerCache}
                                overscanRowCount={20}
                                rowCount={items.length}
                                rowHeight={cellMeasurerCache.rowHeight}
                                rowRenderer={renderRow}
                                ref={listRef as any}
                                id="PlayerInspectorList"
                                onScroll={() => {
                                    // TRICKY: There is no way to know for sure whether the scroll is directly from user input
                                    // As such we only pause scrolling if we the last scroll triggered wasn't by the auto-scroller
                                    // and the user is currently hovering over the list
                                    if (!scrolledByJsFlag.current && mouseHoverRef.current) {
                                        setSyncScrollPaused(true)
                                    }
                                    scrolledByJsFlag.current = false
                                }}
                            />
                        )}
                    </AutoSizer>
                    {syncScrollPaused && (
                        <div className="absolute bottom-2 left-1/2 translate-x-[-50%] bg-bg-3000">
                            <LemonButton
                                type="secondary"
                                onClick={() => {
                                    if (listRef.current) {
                                        listRef.current.scrollToRow(playbackIndicatorIndex)
                                    }
                                    // Tricky: Need to dely to make sure the row scrolled has finished
                                    setTimeout(() => setSyncScrollPaused(false), 100)
                                }}
                            >
                                Sync scrolling
                            </LemonButton>
                        </div>
                    )}
                </div>
            ) : tabsState[tab] === 'loading' ? (
                <div className="p-2">
                    <LemonSkeleton className="my-1 h-8" repeat={20} fade />
                </div>
            ) : tabsState[tab] === 'ready' ? (
                // If we are "ready" but with no results this must mean some results are filtered out
                <div className="p-16 text-center text-muted-alt">No results matching your filters.</div>
            ) : (
                <div className="p-16 text-center text-muted-alt">
                    {tab === SessionRecordingPlayerTab.CONSOLE ? (
                        <EmptyConsoleTab captureConsoleLogOptIn={currentTeam?.capture_console_log_opt_in || false} />
                    ) : tab === SessionRecordingPlayerTab.NETWORK ? (
                        <EmptyNetworkTab
                            captureNetworkFeatureAvailable={performanceAvailable}
                            captureNetworkLogOptIn={performanceEnabled}
                            recordingURL={sessionPlayerMetaData?.start_url}
                        />
                    ) : (
                        'No results found in this recording.'
                    )}
                </div>
            )}
        </div>
    )
}
