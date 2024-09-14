import { IconBug, IconDashboard, IconInfo, IconTerminal } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonSelect, LemonTabs, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconUnverifiedEvent } from 'lib/lemon-ui/icons'
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

export const TabToIcon = {
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
        <LemonTabs
            size="small"
            activeKey={tab}
            onChange={(tabId) => setTab(tabId)}
            tabs={tabs.map((tabId) => {
                const TabIcon = TabToIcon[tabId]
                return {
                    key: tabId,
                    label: (
                        <div className="flex items-center gap-1">
                            {TabIcon ? (
                                tabsState[tabId] === 'loading' ? (
                                    <Spinner textColored />
                                ) : (
                                    <TabIcon />
                                )
                            ) : undefined}
                            <span>{capitalizeFirstLetter(tabId)}</span>
                        </div>
                    ),
                }
            })}
        />
    )
}

export function PlayerInspectorControls(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const inspectorLogic = playerInspectorLogic(logicProps)
    const { tab, windowIdFilter, windowIds, showMatchingEventsFilter } = useValues(inspectorLogic)
    const { setWindowIdFilter, setTab } = useActions(inspectorLogic)
    const { showOnlyMatching, miniFilters, searchQuery } = useValues(playerSettingsLogic)
    const { setShowOnlyMatching, setMiniFilter, setSearchQuery } = useActions(playerSettingsLogic)

    const mode = logicProps.mode ?? SessionRecordingPlayerMode.Standard

    const { featureFlags } = useValues(featureFlagLogic)

    const inspectorTabs = [
        SessionRecordingPlayerTab.ALL,
        SessionRecordingPlayerTab.EVENTS,
        SessionRecordingPlayerTab.CONSOLE,
        SessionRecordingPlayerTab.NETWORK,
    ]
    if (window.IMPERSONATED_SESSION || featureFlags[FEATURE_FLAGS.SESSION_REPLAY_DOCTOR]) {
        inspectorTabs.push(SessionRecordingPlayerTab.DOCTOR)
    } else {
        // ensure we've not left the doctor tab in the tabs state
        if (tab === SessionRecordingPlayerTab.DOCTOR) {
            setTab(SessionRecordingPlayerTab.ALL)
        }
    }

    if (mode === SessionRecordingPlayerMode.Sharing) {
        // Events can't be loaded in sharing mode
        inspectorTabs.splice(1, 1)
        // Doctor tab is not available in sharing mode
        inspectorTabs.pop()
    }

    return (
        <div className="bg-bg-3000 border-b pb-2">
            <div className="flex flex-nowrap">
                <div className="w-2.5 mb-2 border-b shrink-0" />
                <TabButtons tabs={inspectorTabs} logicProps={logicProps} />
                <div className="flex flex-1 border-b shrink-0 mb-2" />
            </div>

            <div className="flex px-2 gap-x-3 flex-wrap gap-y-1">
                <div className="flex flex-1 items-center">
                    <LemonInput
                        size="xsmall"
                        onChange={(e) => setSearchQuery(e)}
                        placeholder="Search..."
                        type="search"
                        value={searchQuery}
                        fullWidth
                        className="min-w-60"
                        suffix={
                            <Tooltip title={<InspectorSearchInfo />}>
                                <IconInfo />
                            </Tooltip>
                        }
                    />
                </div>

                <div
                    className="flex items-center gap-1 flex-wrap font-medium text-primary-alt"
                    data-attr="mini-filters"
                >
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

                {windowIds.length > 1 ? (
                    <div className="flex items-center gap-2">
                        <LemonSelect
                            size="xsmall"
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
                            tooltip="Each recording window translates to a distinct browser tab or window."
                        />
                    </div>
                ) : null}

                {showMatchingEventsFilter ? (
                    <div className="flex items-center gap-1">
                        <LemonCheckbox checked={showOnlyMatching} size="small" onChange={setShowOnlyMatching} />
                        <span className="flex whitespace-nowrap text-xs gap-1">
                            Only events matching filters
                            <Tooltip
                                title="Display only the events that match the global filter."
                                className="text-base text-muted-alt"
                            >
                                <IconInfo />
                            </Tooltip>
                        </span>
                    </div>
                ) : null}
            </div>
        </div>
    )
}
