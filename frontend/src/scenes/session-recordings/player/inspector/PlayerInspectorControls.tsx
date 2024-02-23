import { IconBug, IconClock, IconDashboard, IconInfo, IconPause, IconTerminal, IconX } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonSelect, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconPlayCircle, IconUnverifiedEvent } from 'lib/lemon-ui/icons'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { IconWindow } from 'scenes/session-recordings/player/icons'

import { SessionRecordingPlayerTab } from '~/types'

import { playerSettingsLogic } from '../playerSettingsLogic'
import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerLogicProps,
    SessionRecordingPlayerMode,
} from '../sessionRecordingPlayerLogic'
import { InspectorSearchInfo } from './components/InspectorSearchInfo'
import { playerInspectorLogic } from './playerInspectorLogic'

const TabToIcon = {
    [SessionRecordingPlayerTab.ALL]: undefined,
    [SessionRecordingPlayerTab.EVENTS]: IconUnverifiedEvent,
    [SessionRecordingPlayerTab.CONSOLE]: IconTerminal,
    [SessionRecordingPlayerTab.NETWORK]: IconDashboard,
    [SessionRecordingPlayerTab.DOCTOR]: IconBug,
}

function TabButtons({
    tabs,
    logicProps,
}: {
    tabs: SessionRecordingPlayerTab[]
    logicProps: SessionRecordingPlayerLogicProps
}): JSX.Element {
    const inspectorLogic = playerInspectorLogic(logicProps)
    const { tab, tabsState } = useValues(inspectorLogic)
    const { setTab } = useActions(inspectorLogic)

    return (
        <>
            {tabs.map((tabId) => {
                const TabIcon = TabToIcon[tabId]
                return (
                    <LemonButton
                        key={tabId}
                        size="small"
                        // We want to indicate the tab is loading, but not disable it so we just override the icon here
                        icon={
                            TabIcon ? tabsState[tabId] === 'loading' ? <Spinner textColored /> : <TabIcon /> : undefined
                        }
                        active={tab === tabId}
                        onClick={() => setTab(tabId)}
                    >
                        {capitalizeFirstLetter(tabId)}
                    </LemonButton>
                )
            })}
        </>
    )
}

export function PlayerInspectorControls({ onClose }: { onClose: () => void }): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const inspectorLogic = playerInspectorLogic(logicProps)
    const { tab, windowIdFilter, syncScrollingPaused, windowIds, showMatchingEventsFilter } = useValues(inspectorLogic)
    const { setWindowIdFilter, setSyncScrollPaused, setTab } = useActions(inspectorLogic)
    const { showOnlyMatching, timestampMode, miniFilters, syncScroll, searchQuery } = useValues(playerSettingsLogic)
    const { setShowOnlyMatching, setTimestampMode, setMiniFilter, setSyncScroll, setSearchQuery } =
        useActions(playerSettingsLogic)

    const mode = logicProps.mode ?? SessionRecordingPlayerMode.Standard

    const { featureFlags } = useValues(featureFlagLogic)

    const tabs = [
        SessionRecordingPlayerTab.ALL,
        SessionRecordingPlayerTab.EVENTS,
        SessionRecordingPlayerTab.CONSOLE,
        SessionRecordingPlayerTab.NETWORK,
    ]
    if (window.IMPERSONATED_SESSION || featureFlags[FEATURE_FLAGS.SESSION_REPLAY_DOCTOR]) {
        tabs.push(SessionRecordingPlayerTab.DOCTOR)
    } else {
        // ensure we've not left the doctor tab in the tabs state
        if (tab === SessionRecordingPlayerTab.DOCTOR) {
            setTab(SessionRecordingPlayerTab.ALL)
        }
    }

    if (mode === SessionRecordingPlayerMode.Sharing) {
        // Events can't be loaded in sharing mode
        tabs.splice(1, 1)
        // Doctor tab is not available in sharing mode
        tabs.pop()
    }

    return (
        <div className="bg-side p-2 space-y-2 border-b">
            <div className="flex justify-between gap-2 flex-nowrap">
                <div className="flex flex-1 items-center gap-1">
                    <TabButtons tabs={tabs} logicProps={logicProps} />
                </div>
                <LemonButton size="small" icon={<IconX />} onClick={onClose} />
            </div>

            <div className="flex items-center gap-1 flex-wrap font-medium text-primary-alt" data-attr="mini-filters">
                {miniFilters.map((filter) => (
                    <LemonButton
                        key={filter.key}
                        size="small"
                        noPadding
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

            <div className="flex items-center gap-8 justify-between">
                <div className="flex items-center gap-2 flex-1">
                    <div className="flex flex-1">
                        <LemonInput
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

                <div className="flex items-center gap-1">
                    <LemonButton
                        size="small"
                        noPadding
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
                            <IconClock className="text-lg" />
                        </span>
                    </LemonButton>

                    <LemonButton
                        size="small"
                        noPadding
                        active={syncScroll}
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
