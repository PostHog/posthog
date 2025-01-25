import {
    BaseIcon,
    IconCheck,
    IconDashboard,
    IconGear,
    IconInfo,
    IconSearch,
    IconStethoscope,
    IconTerminal,
} from '@posthog/icons'
import { LemonButton, LemonInput, SideAction, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconChevronRight, IconUnverifiedEvent } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { useEffect, useState } from 'react'
import { SettingsBar, SettingsButton, SettingsToggle } from 'scenes/session-recordings/components/PanelSettings'
import { miniFiltersLogic, SharedListMiniFilter } from 'scenes/session-recordings/player/inspector/miniFiltersLogic'
import {
    InspectorListItem,
    playerInspectorLogic,
} from 'scenes/session-recordings/player/inspector/playerInspectorLogic'
import { teamLogic } from 'scenes/teamLogic'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'
import { FilterableInspectorListItemTypes } from '~/types'

import { sessionRecordingPlayerLogic, SessionRecordingPlayerMode } from '../sessionRecordingPlayerLogic'
import { InspectorSearchInfo } from './components/InspectorSearchInfo'

function sideActionForType({
    miniFilters,
    setMiniFilter,
    allItemsByMiniFilterKey,
}: {
    miniFilters: SharedListMiniFilter[]
    setMiniFilter: (key: string, enabled: boolean) => void
    allItemsByMiniFilterKey: Record<string, InspectorListItem[]>
}): SideAction {
    return {
        icon: <IconChevronRight className="rotate-90" />,
        dropdown: {
            closeOnClickInside: false,
            overlay: (
                <>
                    {miniFilters.map(
                        // without setting fontVariant to none a single digit number between brackets gets rendered as a ligature 🤷
                        (filter: SharedListMiniFilter) => {
                            return (
                                <LemonButton
                                    fullWidth
                                    size="xsmall"
                                    key={filter.name}
                                    icon={
                                        filter.enabled ? (
                                            <IconCheck className="text-sm" />
                                        ) : (
                                            <BaseIcon className="text-sm" />
                                        )
                                    }
                                    status={filter.enabled ? 'danger' : 'default'}
                                    onClick={() => {
                                        setMiniFilter(filter.key, !filter.enabled)
                                    }}
                                    tooltip={filter.tooltip}
                                    active={filter.enabled}
                                >
                                    <div className="flex flex-row w-full items-center justify-between">
                                        <span>{filter.name}&nbsp;</span>
                                        <span
                                            // without setting fontVariant to none a single digit number between brackets gets rendered as a ligature 🤷
                                            // eslint-disable-next-line react/forbid-dom-props
                                            style={{ fontVariant: 'none' }}
                                        >
                                            (<span>{allItemsByMiniFilterKey[filter.key]?.length ?? 0}</span>)
                                        </span>
                                    </div>
                                </LemonButton>
                            )
                        }
                    )}
                </>
            ),
        },
    }
}

function FilterSettingsButton({
    type,
    icon,
    disabledReason,
    hasFilterableItems,
    upsellSideAction,
}: {
    type: FilterableInspectorListItemTypes
    icon: JSX.Element
    disabledReason?: string | undefined
    hasFilterableItems?: boolean
    upsellSideAction?: SideAction
}): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { allItemsByMiniFilterKey } = useValues(playerInspectorLogic(logicProps))
    const { miniFiltersForType } = useValues(miniFiltersLogic)
    const { setMiniFilter, setMiniFilters } = useActions(miniFiltersLogic)

    const networkFilters = miniFiltersForType(type)?.filter((x) => x.name !== 'All')
    const filterKeys = networkFilters.map((x) => x.key)
    const isEnabled = networkFilters.some((x) => !!x.enabled)

    return (
        <SettingsButton
            sideAction={
                upsellSideAction
                    ? upsellSideAction
                    : hasFilterableItems
                    ? sideActionForType({
                          setMiniFilter,
                          allItemsByMiniFilterKey,
                          miniFilters: networkFilters,
                      })
                    : undefined
            }
            label={capitalizeFirstLetter(type)}
            icon={icon}
            onClick={() => {
                setMiniFilters(filterKeys, !isEnabled)
            }}
            disabledReason={disabledReason}
            active={!hasFilterableItems ? false : isEnabled}
        />
    )
}

function NetworkFilterSettingsButton(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { allItemsByItemType } = useValues(playerInspectorLogic(logicProps))
    const { currentTeam } = useValues(teamLogic)
    const { openSettingsPanel } = useActions(sidePanelSettingsLogic)

    const hasNetworkItems = allItemsByItemType[FilterableInspectorListItemTypes.NETWORK]?.length > 0

    return (
        <FilterSettingsButton
            type={FilterableInspectorListItemTypes.NETWORK}
            icon={<IconDashboard />}
            // we disable the filter toggle-all when there are no items
            disabledReason={!hasNetworkItems ? 'There are no network requests in this recording' : undefined}
            hasFilterableItems={hasNetworkItems}
            // if there are no results and the feature is disabled, then we'd upsell
            upsellSideAction={
                !hasNetworkItems && !currentTeam?.capture_performance_opt_in
                    ? {
                          icon: <IconChevronRight className="rotate-90" />,

                          dropdown: {
                              closeOnClickInside: false,
                              overlay: (
                                  <LemonButton
                                      icon={<IconGear />}
                                      fullWidth
                                      size="xsmall"
                                      onClick={() =>
                                          openSettingsPanel({
                                              sectionId: 'project-replay',
                                              settingId: 'replay-network',
                                          })
                                      }
                                  >
                                      Configure network capture in settings.
                                  </LemonButton>
                              ),
                          },
                      }
                    : undefined
            }
        />
    )
}

function ConsoleFilterSettingsButton(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { allItemsByItemType } = useValues(playerInspectorLogic(logicProps))
    const { currentTeam } = useValues(teamLogic)
    const { openSettingsPanel } = useActions(sidePanelSettingsLogic)

    const hasConsoleItems = allItemsByItemType[FilterableInspectorListItemTypes.CONSOLE]?.length > 0

    return (
        <FilterSettingsButton
            type={FilterableInspectorListItemTypes.CONSOLE}
            icon={<IconTerminal />}
            // we disable the filter toggle-all when there are no items
            disabledReason={!hasConsoleItems ? 'There are no console logs in this recording' : undefined}
            hasFilterableItems={hasConsoleItems}
            // if there are no results and the feature is disabled, then we'd upsell
            upsellSideAction={
                !hasConsoleItems && !currentTeam?.capture_console_log_opt_in
                    ? {
                          icon: <IconChevronRight className="rotate-90" />,

                          dropdown: {
                              closeOnClickInside: false,
                              overlay: (
                                  <LemonButton
                                      icon={<IconGear />}
                                      fullWidth
                                      size="xsmall"
                                      onClick={() =>
                                          openSettingsPanel({
                                              sectionId: 'project-replay',
                                              settingId: 'replay',
                                          })
                                      }
                                  >
                                      Configure console log capture in settings.
                                  </LemonButton>
                              ),
                          },
                      }
                    : undefined
            }
        />
    )
}

function EventsFilterSettingsButton(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { allItemsByItemType } = useValues(playerInspectorLogic(logicProps))

    const hasEventItems = allItemsByItemType[FilterableInspectorListItemTypes.EVENTS]?.length > 0

    return (
        <FilterSettingsButton
            type={FilterableInspectorListItemTypes.EVENTS}
            icon={<IconUnverifiedEvent />}
            // we disable the filter toggle-all when there are no items
            disabledReason={!hasEventItems ? 'There are no events in this recording' : undefined}
            hasFilterableItems={hasEventItems}
            // there is no event upsell currently
            upsellSideAction={undefined}
        />
    )
}

export function PlayerInspectorControls(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { searchQuery, miniFiltersByKey } = useValues(miniFiltersLogic)
    const { setSearchQuery, setMiniFilter } = useActions(miniFiltersLogic)

    const mode = logicProps.mode ?? SessionRecordingPlayerMode.Standard

    const { featureFlags } = useValues(featureFlagLogic)

    const [showSearch, setShowSearch] = useState(false)

    useEffect(() => {
        if (!window.IMPERSONATED_SESSION && !featureFlags[FEATURE_FLAGS.SESSION_REPLAY_DOCTOR]) {
            // ensure we've not left the doctor active
            setMiniFilter('doctor', false)
        }
    }, [featureFlags, setMiniFilter])

    return (
        <div className="flex">
            <SettingsBar border="bottom" className="justify-end">
                {mode !== SessionRecordingPlayerMode.Sharing && <EventsFilterSettingsButton />}
                <ConsoleFilterSettingsButton />
                <NetworkFilterSettingsButton />
                {(window.IMPERSONATED_SESSION || featureFlags[FEATURE_FLAGS.SESSION_REPLAY_DOCTOR]) &&
                    mode !== SessionRecordingPlayerMode.Sharing && (
                        <SettingsToggle
                            title="Doctor events help diagnose the health of a recording, and are used by PostHog support"
                            icon={<IconStethoscope />}
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
