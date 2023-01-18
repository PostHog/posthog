import { LemonButton, LemonInput, LemonSelect, LemonCheckbox } from '@posthog/lemon-ui'
import { Tooltip } from 'antd'
import { useValues, useActions } from 'kea'
import {
    IconInfo,
    IconSchedule,
    IconPlayCircle,
    IconGauge,
    IconTerminal,
    IconUnverifiedEvent,
} from 'lib/components/icons'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { useMemo } from 'react'
import { SessionRecordingPlayerTab } from '~/types'
import { IconWindow } from '../../icons'
import { playerSettingsLogic } from '../../playerSettingsLogic'
import { SessionRecordingPlayerLogicProps } from '../../sessionRecordingPlayerLogic'
import { playerInspectorLogic } from '../playerInspectorLogic'

const TabToIcon = {
    [SessionRecordingPlayerTab.ALL]: undefined,
    [SessionRecordingPlayerTab.EVENTS]: IconUnverifiedEvent,
    [SessionRecordingPlayerTab.CONSOLE]: IconTerminal,
    [SessionRecordingPlayerTab.NETWORK]: IconGauge,
}

export function PlayerInspectorControls({
    sessionRecordingId,
    playerKey,
    matching,
}: SessionRecordingPlayerLogicProps): JSX.Element {
    const logicProps = { sessionRecordingId, playerKey }
    const { windowIdFilter, tab, searchQuery, syncScroll, tabsState, windowIds } = useValues(
        playerInspectorLogic(logicProps)
    )
    const { setWindowIdFilter, setTab, setSearchQuery, setSyncScroll } = useActions(playerInspectorLogic(logicProps))
    const { showOnlyMatching, timestampMode, miniFilters } = useValues(playerSettingsLogic)
    const { setShowOnlyMatching, setTimestampMode, setMiniFilter } = useActions(playerSettingsLogic)

    const { featureFlags } = useValues(featureFlagLogic)
    const inspectorPerformance = !!featureFlags[FEATURE_FLAGS.RECORDINGS_INSPECTOR_PERFORMANCE]

    const tabs = useMemo(() => {
        return [
            SessionRecordingPlayerTab.ALL,
            SessionRecordingPlayerTab.EVENTS,
            SessionRecordingPlayerTab.CONSOLE,
            inspectorPerformance ? SessionRecordingPlayerTab.NETWORK : undefined,
        ].filter(Boolean) as SessionRecordingPlayerTab[]
    }, [inspectorPerformance])

    return (
        <div className="bg-side p-2 space-y-2">
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
                                            <Spinner monocolor />
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
                    />
                </div>
                {windowIds.length > 1 ? (
                    <div className="flex items-center gap-2 flex-wrap">
                        <LemonSelect
                            size="small"
                            data-attr="player-window-select"
                            value={windowIdFilter ?? undefined}
                            onChange={(val) => setWindowIdFilter(val || null)}
                            options={[
                                {
                                    value: undefined,
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
        </div>
    )
}
