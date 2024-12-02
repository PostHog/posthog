import {
    BaseIcon,
    IconBug,
    IconCheck,
    IconDashboard,
    IconGear,
    IconInfo,
    IconSearch,
    IconTerminal,
} from '@posthog/icons'
import { LemonButton, LemonInput, LemonMenuItem, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconUnverifiedEvent } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { useEffect, useState } from 'react'
import { SettingsBar, SettingsMenu, SettingsToggle } from 'scenes/session-recordings/components/PanelSettings'
import { miniFiltersLogic, SharedListMiniFilter } from 'scenes/session-recordings/player/inspector/miniFiltersLogic'
import { playerInspectorLogic } from 'scenes/session-recordings/player/inspector/playerInspectorLogic'
import { teamLogic } from 'scenes/teamLogic'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'
import { FilterableInspectorListItemTypes } from '~/types'

import { sessionRecordingPlayerLogic, SessionRecordingPlayerMode } from '../sessionRecordingPlayerLogic'
import { InspectorSearchInfo } from './components/InspectorSearchInfo'

export const TabToIcon = {
    [FilterableInspectorListItemTypes.EVENTS]: IconUnverifiedEvent,
    [FilterableInspectorListItemTypes.CONSOLE]: IconTerminal,
    [FilterableInspectorListItemTypes.NETWORK]: IconDashboard,
    [FilterableInspectorListItemTypes.DOCTOR]: IconBug,
}

export function PlayerInspectorControls(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { allItemsByMiniFilterKey, allItemsByItemType } = useValues(playerInspectorLogic(logicProps))
    const { searchQuery, miniFiltersForType, miniFiltersByKey } = useValues(miniFiltersLogic)
    const { setSearchQuery, setMiniFilter } = useActions(miniFiltersLogic)
    const { currentTeam } = useValues(teamLogic)
    const { openSettingsPanel } = useActions(sidePanelSettingsLogic)

    const mode = logicProps.mode ?? SessionRecordingPlayerMode.Standard

    const { featureFlags } = useValues(featureFlagLogic)

    const [showSearch, setShowSearch] = useState(false)

    useEffect(() => {
        if (!window.IMPERSONATED_SESSION && !featureFlags[FEATURE_FLAGS.SESSION_REPLAY_DOCTOR]) {
            // ensure we've not left the doctor active
            setMiniFilter('doctor', false)
        }
    }, [])

    function filterMenuForType(type: FilterableInspectorListItemTypes): LemonMenuItem[] {
        return miniFiltersForType(type)
            ?.filter((x) => x.name !== 'All')
            .map(
                // without setting fontVariant to none a single digit number between brackets gets rendered as a ligature 🤷
                (filter: SharedListMiniFilter) =>
                    ({
                        label: (
                            <div className="flex flex-row w-full items-center justify-between">
                                <span>{filter.name}&nbsp;</span>
                                <span
                                    // without setting fontVariant to none a single digit number between brackets gets rendered as a ligature 🤷
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ fontVariant: 'none' }}
                                >
                                    ({allItemsByMiniFilterKey[filter.key]?.length ?? 0})
                                </span>
                            </div>
                        ),
                        icon: filter.enabled ? <IconCheck className="text-sm" /> : <BaseIcon className="text-sm" />,
                        status: filter.enabled ? 'danger' : 'default',
                        onClick: () => {
                            setMiniFilter(filter.key, !filter.enabled)
                        },
                        tooltip: filter.tooltip,
                        active: filter.enabled,
                    } satisfies LemonMenuItem)
            )
    }

    const eventsFilters: LemonMenuItem[] = filterMenuForType(FilterableInspectorListItemTypes.EVENTS)
    const consoleFilters: LemonMenuItem[] = filterMenuForType(FilterableInspectorListItemTypes.CONSOLE)
    const hasConsoleItems = allItemsByItemType[FilterableInspectorListItemTypes.CONSOLE]?.length > 0
    const networkFilters: LemonMenuItem[] = filterMenuForType(FilterableInspectorListItemTypes.NETWORK)
    const hasNetworkItems = allItemsByItemType[FilterableInspectorListItemTypes.NETWORK]?.length > 0

    return (
        <div className="flex">
            <SettingsBar border="bottom" className="justify-end">
                {mode !== SessionRecordingPlayerMode.Sharing && (
                    <SettingsMenu
                        items={eventsFilters}
                        label={capitalizeFirstLetter(FilterableInspectorListItemTypes.EVENTS)}
                        icon={<IconUnverifiedEvent />}
                        closeOnClickInside={false}
                    />
                )}
                <SettingsMenu
                    items={consoleFilters}
                    label={capitalizeFirstLetter(FilterableInspectorListItemTypes.CONSOLE)}
                    icon={<IconTerminal />}
                    isAvailable={hasConsoleItems || !!currentTeam?.capture_console_log_opt_in}
                    whenUnavailable={{
                        label: <p className="text-muted text-center">Configure console log capture in settings.</p>,
                        onClick: () => openSettingsPanel({ sectionId: 'project-replay', settingId: 'replay' }),
                        icon: <IconGear />,
                    }}
                    closeOnClickInside={false}
                />
                <SettingsMenu
                    items={networkFilters}
                    label={capitalizeFirstLetter(FilterableInspectorListItemTypes.NETWORK)}
                    icon={<IconDashboard />}
                    isAvailable={hasNetworkItems || !!currentTeam?.capture_performance_opt_in}
                    whenUnavailable={{
                        label: <p className="text-muted text-center">Configure network capture in settings.</p>,
                        onClick: () => openSettingsPanel({ sectionId: 'project-replay', settingId: 'replay-network' }),
                        icon: <IconGear />,
                    }}
                    closeOnClickInside={false}
                />
                {(window.IMPERSONATED_SESSION || featureFlags[FEATURE_FLAGS.SESSION_REPLAY_DOCTOR]) &&
                    mode !== SessionRecordingPlayerMode.Sharing && (
                        <SettingsToggle
                            title="Doctor events help diagnose the health of a recording, and are used by PostHog support"
                            icon={<IconBug />}
                            label="Doctor"
                            active={!!miniFiltersByKey['doctor']?.enabled}
                            onClick={() => setMiniFilter('doctor', !miniFiltersByKey['doctor']?.enabled)}
                        />
                    )}
                <LemonButton
                    icon={<IconSearch />}
                    size="xsmall"
                    onClick={() => {
                        const newState = !showSearch
                        setShowSearch(newState)
                        if (!newState) {
                            // clear the search when we're hiding the search bar
                            setSearchQuery('')
                        }
                    }}
                    status={showSearch ? 'danger' : 'default'}
                    title="Search"
                    className="rounded-[0px]"
                />
            </SettingsBar>
            {showSearch && (
                <div className="flex px-2 py-1">
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
            )}
        </div>
    )
}
