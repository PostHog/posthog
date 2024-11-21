import { IconBug, IconCheck, IconDashboard, IconInfo, IconSearch, IconTerminal } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonInput,
    LemonMenu,
    LemonMenuItem,
    LemonSelect,
    Tooltip,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconUnverifiedEvent } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userPreferencesLogic } from 'lib/logic/userPreferencesLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { useState } from 'react'
import { IconWindow } from 'scenes/session-recordings/player/icons'
import { miniFiltersLogic, SharedListMiniFilter } from 'scenes/session-recordings/player/inspector/miniFiltersLogic'

import { SessionRecordingPlayerTab } from '~/types'

import { sessionRecordingPlayerLogic, SessionRecordingPlayerMode } from '../sessionRecordingPlayerLogic'
import { InspectorSearchInfo } from './components/InspectorSearchInfo'
import { playerInspectorLogic } from './playerInspectorLogic'

/**
 * TODO only one window filter necessary!
 * TODO remove tab code entirely
 * TODO update tests
 * TODO how do we map existing "all" filters someone has set or just ignore
 * TODO show counts alongside selectors so folk know whether to click them
 */

function HideProperties(): JSX.Element | null {
    const { miniFiltersForTab } = useValues(miniFiltersLogic)
    const { hidePostHogPropertiesInTable } = useValues(userPreferencesLogic)
    const { setHidePostHogPropertiesInTable } = useActions(userPreferencesLogic)

    return miniFiltersForTab(SessionRecordingPlayerTab.EVENTS).some((x) => x.enabled) ? (
        <LemonCheckbox
            checked={hidePostHogPropertiesInTable}
            label="Hide PostHog properties"
            bordered
            onChange={setHidePostHogPropertiesInTable}
            size="xsmall"
        />
    ) : null
}

function WindowSelector(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const inspectorLogic = playerInspectorLogic(logicProps)
    const { windowIdFilter, windowIds } = useValues(inspectorLogic)
    const { setWindowIdFilter } = useActions(inspectorLogic)

    return windowIds.length > 1 ? (
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
    ) : (
        // returns an empty div to keep spacing/positioning consistent
        <div> </div>
    )
}

export const TabToIcon = {
    [SessionRecordingPlayerTab.EVENTS]: IconUnverifiedEvent,
    [SessionRecordingPlayerTab.CONSOLE]: IconTerminal,
    [SessionRecordingPlayerTab.NETWORK]: IconDashboard,
    [SessionRecordingPlayerTab.DOCTOR]: IconBug,
}

/**
 * TODO
 *
 * tabsState to show loading
 */

export function PlayerInspectorControls(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    // const inspectorLogic = playerInspectorLogic(logicProps)
    // const { showMatchingEventsFilter } = useValues(inspectorLogic)
    const {
        //showOnlyMatching,
        searchQuery,
        miniFiltersForTab,
        miniFiltersByKey,
    } = useValues(miniFiltersLogic)
    const {
        //setShowOnlyMatching,
        setSearchQuery,
        setMiniFilter,
    } = useActions(miniFiltersLogic)

    const mode = logicProps.mode ?? SessionRecordingPlayerMode.Standard

    const { featureFlags } = useValues(featureFlagLogic)

    const [showSearch, setShowSearch] = useState(false)

    if (!window.IMPERSONATED_SESSION && !featureFlags[FEATURE_FLAGS.SESSION_REPLAY_DOCTOR]) {
        // ensure we've not left the doctor tab in the tabs state
    }

    const eventsFilters: LemonMenuItem[] = miniFiltersForTab(SessionRecordingPlayerTab.EVENTS)
        ?.filter((x) => x.name !== 'All')
        .map(
            (filter: SharedListMiniFilter) =>
                ({
                    label: filter.name,
                    icon: filter.enabled ? <IconCheck className="text-sm" /> : undefined,
                    status: filter.enabled ? 'danger' : 'default',
                    onClick: () => {
                        setMiniFilter(filter.key, !filter.enabled)
                    },
                    tooltip: filter.tooltip,
                    active: filter.enabled,
                } satisfies LemonMenuItem)
        )

    const consoleFilters: LemonMenuItem[] = miniFiltersForTab(SessionRecordingPlayerTab.CONSOLE)
        ?.filter((x) => x.name !== 'All')
        .map(
            (filter: SharedListMiniFilter) =>
                ({
                    label: filter.name,
                    icon: filter.enabled ? <IconCheck className="text-sm" /> : undefined,
                    status: filter.enabled ? 'danger' : 'default',
                    onClick: () => {
                        setMiniFilter(filter.key, !filter.enabled)
                    },
                    tooltip: filter.tooltip,
                    active: filter.enabled,
                } satisfies LemonMenuItem)
        )

    const networkFilters: LemonMenuItem[] = miniFiltersForTab(SessionRecordingPlayerTab.NETWORK)
        ?.filter((x) => x.name !== 'All')
        .map(
            (filter: SharedListMiniFilter) =>
                ({
                    label: filter.name,
                    icon: filter.enabled ? <IconCheck className="text-sm" /> : undefined,
                    status: filter.enabled ? 'danger' : 'default',
                    onClick: () => {
                        setMiniFilter(filter.key, !filter.enabled)
                    },
                    tooltip: filter.tooltip,
                    active: filter.enabled,
                } satisfies LemonMenuItem)
        )

    return (
        <div className="bg-bg-3000 border-b pb-2">
            <div className="flex flex-nowrap">
                <div className="w-2.5 mb-2 border-b shrink-0" />
                <div className="flex flex-1 border-b shrink-0 mb-2 mr-2 items-center justify-end font-light">
                    {mode !== SessionRecordingPlayerMode.Sharing && (
                        <LemonMenu buttonSize="xsmall" closeOnClickInside={false} items={eventsFilters}>
                            <LemonButton
                                status={eventsFilters.some((cf) => !!cf.active) ? 'danger' : 'default'}
                                size="xsmall"
                                icon={<IconUnverifiedEvent />}
                            >
                                {capitalizeFirstLetter(SessionRecordingPlayerTab.EVENTS)}
                            </LemonButton>
                        </LemonMenu>
                    )}
                    <LemonMenu buttonSize="xsmall" closeOnClickInside={false} items={consoleFilters}>
                        <LemonButton
                            status={consoleFilters.some((cf) => !!cf.active) ? 'danger' : 'default'}
                            size="xsmall"
                            icon={<IconTerminal />}
                        >
                            {capitalizeFirstLetter(SessionRecordingPlayerTab.CONSOLE)}
                        </LemonButton>
                    </LemonMenu>
                    <LemonMenu buttonSize="xsmall" closeOnClickInside={false} items={networkFilters}>
                        <LemonButton
                            status={networkFilters.some((cf) => !!cf.active) ? 'danger' : 'default'}
                            size="xsmall"
                            icon={<IconDashboard />}
                        >
                            {capitalizeFirstLetter(SessionRecordingPlayerTab.NETWORK)}
                        </LemonButton>
                    </LemonMenu>
                    {(window.IMPERSONATED_SESSION || featureFlags[FEATURE_FLAGS.SESSION_REPLAY_DOCTOR]) &&
                        mode !== SessionRecordingPlayerMode.Sharing && (
                            <Tooltip title="Doctor events help diagnose the health of a recording, and are used by PostHog support">
                                <LemonButton
                                    icon={<IconBug />}
                                    size="xsmall"
                                    onClick={() => setMiniFilter('doctor', !miniFiltersByKey['doctor']?.enabled)}
                                    status={miniFiltersByKey['doctor']?.enabled ? 'danger' : 'default'}
                                >
                                    Doctor
                                </LemonButton>
                            </Tooltip>
                        )}
                    <LemonButton
                        icon={<IconSearch />}
                        size="xsmall"
                        onClick={() => setShowSearch(!showSearch)}
                        status={showSearch ? 'danger' : 'default'}
                    />
                </div>
            </div>

            <div className="flex px-2 gap-x-3 flex-wrap gap-y-1">
                {showSearch && (
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
                )}

                <div className="flex flex-row justify-between w-full font-light text-small">
                    <WindowSelector />
                    <HideProperties />
                </div>

                {/*{showMatchingEventsFilter ? (*/}
                {/*    <div className="flex items-center gap-1">*/}
                {/*        <LemonCheckbox checked={showOnlyMatching} size="small" onChange={setShowOnlyMatching} />*/}
                {/*        <span className="flex whitespace-nowrap text-xs gap-1">*/}
                {/*            Only events matching filters*/}
                {/*            <Tooltip*/}
                {/*                title="Display only the events that match the global filter."*/}
                {/*                className="text-base text-muted-alt"*/}
                {/*            >*/}
                {/*                <IconInfo />*/}
                {/*            </Tooltip>*/}
                {/*        </span>*/}
                {/*    </div>*/}
                {/*) : null}*/}
            </div>
        </div>
    )
}
