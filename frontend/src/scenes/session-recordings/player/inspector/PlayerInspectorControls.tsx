import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import {
    BaseIcon,
    IconCheck,
    IconChevronDown,
    IconChevronRight,
    IconComment,
    IconCopy,
    IconDashboard,
    IconDownload,
    IconEllipsis,
    IconGear,
    IconInfo,
    IconLive,
    IconStethoscope,
    IconTerminal,
} from '@posthog/icons'
import { LemonButton, LemonInput, LemonMenu, LemonMenuItems, SideAction, Tooltip } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { IconUnverifiedEvent } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { SettingsBar, SettingsButton, SettingsToggle } from 'scenes/session-recordings/components/PanelSettings'
import { SharedListMiniFilter, miniFiltersLogic } from 'scenes/session-recordings/player/inspector/miniFiltersLogic'
import {
    FilterableInspectorListItemTypes,
    InspectorListItem,
    playerInspectorLogic,
} from 'scenes/session-recordings/player/inspector/playerInspectorLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SessionRecordingPlayerMode, sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
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
                                    data-attr={`player-inspector-${filter.key}-mini-filter-toggle`}
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
    upsellSideAction,
    label,
}: {
    type: FilterableInspectorListItemTypes
    icon: JSX.Element
    disabledReason?: string | undefined
    upsellSideAction?: SideAction
    label?: string
}): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { allItemsByMiniFilterKey, allItemsByItemType } = useValues(playerInspectorLogic(logicProps))
    const { miniFiltersForType } = useValues(miniFiltersLogic)
    const { setMiniFilter, setMiniFilters } = useActions(miniFiltersLogic)

    const filteredMiniFiltersForType = miniFiltersForType(type)?.filter((x) => x.name !== 'All')
    const filterKeys = filteredMiniFiltersForType.map((x) => x.key)
    const isEnabled = filteredMiniFiltersForType.some((x) => !!x.enabled)

    return (
        <SettingsButton
            sideAction={
                upsellSideAction
                    ? upsellSideAction
                    : allItemsByItemType[type]?.length > 1
                      ? sideActionForType({
                            setMiniFilter,
                            allItemsByMiniFilterKey,
                            miniFilters: filteredMiniFiltersForType,
                        })
                      : undefined
            }
            label={label || capitalizeFirstLetter(type)}
            icon={icon}
            onClick={() => {
                setMiniFilters(filterKeys, !isEnabled)
            }}
            disabledReason={disabledReason}
            active={isEnabled}
        />
    )
}

function NetworkFilterSettingsButton(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { allItemsByItemType } = useValues(playerInspectorLogic(logicProps))
    const { currentTeam } = useValues(teamLogic)

    const hasNetworkItems = allItemsByItemType['network']?.length > 0

    return (
        <FilterSettingsButton
            data-attr="player-inspector-network-toggle-all"
            type="network"
            icon={<IconDashboard />}
            // we disable the filter toggle-all when there are no items
            disabledReason={!hasNetworkItems ? 'There are no network requests in this recording' : undefined}
            // if there are no results and the feature is disabled, then we'd upsell
            upsellSideAction={
                !hasNetworkItems && !currentTeam?.capture_performance_opt_in
                    ? {
                          icon: <IconChevronDown />,

                          dropdown: {
                              closeOnClickInside: false,
                              overlay: (
                                  <LemonButton
                                      data-attr="player-inspector-network-upsell"
                                      icon={<IconGear />}
                                      fullWidth
                                      size="xsmall"
                                      to={urls.settings('project-replay', 'replay-network')}
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

    const hasConsoleItems = allItemsByItemType['console']?.length > 0

    return (
        <FilterSettingsButton
            data-attr="player-inspector-console-toggle-all"
            type="console"
            icon={<IconTerminal />}
            // we disable the filter toggle-all when there are no items
            disabledReason={!hasConsoleItems ? 'There are no console logs in this recording' : undefined}
            // if there are no results and the feature is disabled, then we'd upsell
            upsellSideAction={
                !hasConsoleItems && !currentTeam?.capture_console_log_opt_in
                    ? {
                          icon: <IconChevronRight className="rotate-90" />,

                          dropdown: {
                              closeOnClickInside: false,
                              overlay: (
                                  <LemonButton
                                      data-attr="player-inspector-console-upsell"
                                      icon={<IconGear />}
                                      fullWidth
                                      size="xsmall"
                                      to={urls.settings('project-replay', 'replay')}
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

    const hasEventItems = allItemsByItemType['events']?.length > 0

    return (
        <FilterSettingsButton
            data-attr="player-inspector-events-toggle-all"
            type="events"
            icon={<IconUnverifiedEvent />}
            // we disable the filter toggle-all when there are no items
            disabledReason={!hasEventItems ? 'There are no events in this recording' : undefined}
            upsellSideAction={undefined}
        />
    )
}

function CommentsFilterSettingsButton(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { allItemsByItemType } = useValues(playerInspectorLogic(logicProps))

    const hasCommentItems = allItemsByItemType['comment']?.length > 0

    return (
        <FilterSettingsButton
            data-attr="player-inspector-comments-toggle"
            type="comment"
            icon={<IconComment />}
            disabledReason={!hasCommentItems ? 'There are no comments in this recording' : undefined}
            upsellSideAction={undefined}
            label="Comments"
        />
    )
}

function LogsFilterSettingsButton(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { allItemsByItemType, logsLoading, logsLoadError } = useValues(playerInspectorLogic(logicProps))

    const hasLogItems = allItemsByItemType['logs']?.length > 0

    const disabledReason = logsLoading
        ? 'Loading logs...'
        : logsLoadError
          ? 'Failed to load logs for this session'
          : !hasLogItems
            ? 'No logs found for this session'
            : undefined

    return (
        <FilterSettingsButton
            data-attr="player-inspector-logs-toggle-all"
            type="logs"
            icon={<IconLive />}
            disabledReason={disabledReason}
            label="Logs"
        />
    )
}

export function PlayerInspectorControls(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { searchQuery, miniFiltersByKey } = useValues(miniFiltersLogic)
    const { setSearchQuery, setMiniFilter } = useActions(miniFiltersLogic)
    const { displayGroups, logsHasMore } = useValues(playerInspectorLogic(logicProps))
    const { copyVisibleInspectorRows, exportVisibleInspectorRowsJson } = useActions(playerInspectorLogic(logicProps))

    const mode = logicProps.mode ?? SessionRecordingPlayerMode.Standard
    const isSharingMode = mode === SessionRecordingPlayerMode.Sharing
    const hasVisibleRows = displayGroups.length > 0
    const exportDisabledReason = hasVisibleRows ? undefined : 'There are no visible inspector rows to copy or export'
    const exportTriggerTooltip = 'Copy or export the visible inspector rows'
    const exportMenuItems: LemonMenuItems = [
        logsHasMore && {
            title: 'Backend logs are truncated — more logs are available',
            items: [],
            key: 'inspector-export-truncation-notice',
        },
        {
            items: [
                {
                    label: 'Copy visible rows',
                    icon: <IconCopy />,
                    onClick: copyVisibleInspectorRows,
                    disabledReason: exportDisabledReason,
                    tooltip: 'Copy the currently visible rows as text',
                    'data-attr': 'player-inspector-copy-visible-rows',
                },
                {
                    label: 'Download JSON',
                    icon: <IconDownload />,
                    onClick: exportVisibleInspectorRowsJson,
                    disabledReason: exportDisabledReason,
                    tooltip: 'Download the visible rows as a JSON file',
                    'data-attr': 'player-inspector-download-json',
                },
            ],
        },
    ]

    const { featureFlags } = useValues(featureFlagLogic)

    useEffect(() => {
        if (!window.IMPERSONATED_SESSION && !featureFlags[FEATURE_FLAGS.SESSION_REPLAY_DOCTOR]) {
            // ensure we've not left the doctor active
            setMiniFilter('doctor', false)
        }
    }, [featureFlags, setMiniFilter])

    return (
        <div className="flex flex-col">
            <SettingsBar border="bottom" className="justify-end">
                {!isSharingMode && <EventsFilterSettingsButton />}
                <ConsoleFilterSettingsButton />
                <NetworkFilterSettingsButton />
                {featureFlags[FEATURE_FLAGS.SESSION_REPLAY_BACKEND_LOGS] && !isSharingMode && (
                    <LogsFilterSettingsButton />
                )}
                {!isSharingMode && <CommentsFilterSettingsButton />}
                {(window.IMPERSONATED_SESSION || featureFlags[FEATURE_FLAGS.SESSION_REPLAY_DOCTOR]) &&
                    !isSharingMode && (
                        <SettingsToggle
                            data-attr="player-inspector-doctor-toggle"
                            title="Doctor events help diagnose the health of a recording, and are used by PostHog support"
                            icon={<IconStethoscope />}
                            label="Doctor"
                            active={!!miniFiltersByKey['doctor']?.enabled}
                            onClick={() => setMiniFilter('doctor', !miniFiltersByKey['doctor']?.enabled)}
                        />
                    )}
            </SettingsBar>

            <div className="flex px-2 py-1 gap-1">
                <LemonInput
                    data-attr="player-inspector-search-input"
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
                {!isSharingMode ? (
                    <LemonMenu items={exportMenuItems} buttonSize="xsmall" placement="bottom-end">
                        <LemonButton
                            size="xsmall"
                            icon={<IconEllipsis />}
                            tooltip={exportTriggerTooltip}
                            disabledReason={exportDisabledReason}
                            aria-label="Copy or export inspector rows"
                            data-attr="player-inspector-copy-export-menu"
                        />
                    </LemonMenu>
                ) : null}
            </div>
        </div>
    )
}
