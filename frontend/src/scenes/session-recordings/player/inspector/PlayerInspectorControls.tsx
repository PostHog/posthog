import { LemonButton, LemonInput, LemonSelect, LemonCheckbox, Tooltip } from '@posthog/lemon-ui'
import { useValues, useActions } from 'kea'
import {
    IconInfo,
    IconSchedule,
    IconPlayCircle,
    IconGauge,
    IconTerminal,
    IconUnverifiedEvent,
    IconPause,
} from 'lib/lemon-ui/icons'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { capitalizeFirstLetter } from 'lib/utils'
import { SessionRecordingPlayerTab } from '~/types'
import { IconWindow } from 'scenes/session-recordings/player/icons'
import { playerSettingsLogic } from '../playerSettingsLogic'
import { SessionRecordingPlayerMode, sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { playerInspectorLogic } from './playerInspectorLogic'
import { InspectorSearchInfo } from './components/InspectorSearchInfo'

const TabToIcon = {
    [SessionRecordingPlayerTab.ALL]: undefined,
    [SessionRecordingPlayerTab.EVENTS]: IconUnverifiedEvent,
    [SessionRecordingPlayerTab.CONSOLE]: IconTerminal,
    [SessionRecordingPlayerTab.NETWORK]: IconGauge,
}

export function PlayerInspectorControls(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const inspectorLogic = playerInspectorLogic(logicProps)
    const { windowIdFilter, tab, syncScrollingPaused, tabsState, windowIds, showMatchingEventsFilter } =
        useValues(inspectorLogic)
    const { setWindowIdFilter, setTab, setSyncScrollPaused } = useActions(inspectorLogic)
    const { showOnlyMatching, timestampMode, miniFilters, syncScroll, searchQuery } = useValues(playerSettingsLogic)
    const { setShowOnlyMatching, setTimestampMode, setMiniFilter, setSyncScroll, setSearchQuery } =
        useActions(playerSettingsLogic)

    const mode = logicProps.mode ?? SessionRecordingPlayerMode.Standard

    const tabs = [
        SessionRecordingPlayerTab.ALL,
        SessionRecordingPlayerTab.EVENTS,
        SessionRecordingPlayerTab.CONSOLE,
        SessionRecordingPlayerTab.NETWORK,
    ]

    if (mode === SessionRecordingPlayerMode.Sharing) {
        // Events can't be loaded in sharing mode
        tabs.splice(1, 1)
    }

    return (
        <div className="bg-side p-2 space-y-2 border-b">
            <div className="flex justify-between gap-2 flex-wrap">
                <div className="flex flex-1 items-center gap-1">
                    {tabs.map((tabId) => {
                        const TabIcon = TabToIcon[tabId]
                        return (
                            <LemonButton
                                key={tabId}
                                size="small"
                                // We want to indicate the tab is loading, but not disable it so we just override the icon here
                                icon={
                                    TabIcon ? (
                                        tabsState[tabId] === 'loading' ? (
                                            <Spinner textColored />
                                        ) : (
                                            <TabIcon />
                                        )
                                    ) : undefined
                                }
                                status={tab === tabId ? 'primary' : 'primary-alt'}
                                active={tab === tabId}
                                onClick={() => setTab(tabId)}
                            >
                                {capitalizeFirstLetter(tabId)}
                            </LemonButton>
                        )
                    })}
                </div>

                <div className="flex items-center gap-2 flex-1">
                    <LemonInput
                        className="min-w-40"
                        size="small"
                        onChange={(e) => setSearchQuery(e)}
                        placeholder="Search..."
                        type="search"
                        value={searchQuery}
                        fullWidth
                        suffix={
                            <Tooltip title={<InspectorSearchInfo />}>
                                <IconInfo />
                            </Tooltip>
                        }
                    />
                </div>
                {windowIds.length > 1 ? (
                    <div className="flex items-center gap-2 flex-wrap">
                        <LemonSelect
                            size="small"
                            data-attr="player-window-select"
                            value={windowIdFilter}
                            onChange={(val) => setWindowIdFilter(val || null)}
                            options={[
                                {
                                    value: null,
                                    label: 'All windows',
                                    icon: <IconWindow size="small" value="A" className="text-muted" />,
                                },
                                ...windowIds.map((windowId, index) => ({
                                    value: windowId,
                                    label: `Window ${index + 1}`,
                                    icon: <IconWindow size="small" value={index + 1} className="text-muted" />,
                                })),
                            ]}
                        />
                        <Tooltip
                            title="Each recording window translates to a distinct browser tab or window."
                            className="text-base text-muted-alt"
                        >
                            <IconInfo />
                        </Tooltip>
                    </div>
                ) : null}
            </div>

            <div className="flex items-center gap-2 justify-between">
                <div
                    className="flex items-center gap-1 flex-wrap font-medium text-primary-alt"
                    data-attr={'mini-filters'}
                >
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
                            tooltip={filter.tooltip}
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
                        onClick={() => {
                            // If the user has syncScrolling on but it is paused due to interacting with the Inspector, we want to resume it
                            if (syncScroll && syncScrollingPaused) {
                                setSyncScrollPaused(false)
                            } else {
                                // Otherwise we are just toggling the settting
                                setSyncScroll(!syncScroll)
                            }
                        }}
                        tooltipPlacement="left"
                        tooltip={
                            syncScroll && syncScrollingPaused
                                ? 'Synced scrolling is paused - click to resume'
                                : 'Scroll the list in sync with the recording playback'
                        }
                    >
                        {syncScroll && syncScrollingPaused ? (
                            <IconPause className="text-lg m-1" />
                        ) : (
                            <IconPlayCircle className="text-lg m-1" />
                        )}
                    </LemonButton>
                </div>
            </div>
            {showMatchingEventsFilter ? (
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
        </div>
    )
}
