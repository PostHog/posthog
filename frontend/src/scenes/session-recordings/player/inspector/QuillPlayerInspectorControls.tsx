import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import { IconComment, IconDashboard, IconGear, IconInfo, IconLive, IconStethoscope, IconTerminal } from '@posthog/icons'
import {
    Button,
    InputGroup,
    InputGroupAddon,
    InputGroupButton,
    InputGroupInput,
    Popover,
    PopoverContent,
    PopoverTrigger,
} from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { IconUnverifiedEvent } from 'lib/lemon-ui/icons'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { miniFiltersLogic } from 'scenes/session-recordings/player/inspector/miniFiltersLogic'
import {
    FilterableInspectorListItemTypes,
    playerInspectorLogic,
} from 'scenes/session-recordings/player/inspector/playerInspectorLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SessionRecordingPlayerMode, sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { InspectorSearchInfo } from './components/InspectorSearchInfo'
import { QuillInspectorToggle } from './components/QuillInspectorToggle'
import { SessionLogsUnavailableNotice } from './components/SessionLogsUnavailableNotice'

interface InspectorFilterType {
    type: FilterableInspectorListItemTypes
    label: string
    icon: JSX.Element
    dataAttr: string
    tooltip?: string
    disabledReason?: string
    loading?: boolean
    setup?: { label: string; to: string; dataAttr: string }
}

export function QuillPlayerInspectorControls(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const {
        allItemsByItemType,
        allItemsByMiniFilterKey,
        logsLoading,
        logsLoadError,
        logsInitialLoadRequested,
        logsAccessDenied,
    } = useValues(playerInspectorLogic(logicProps))
    const { searchQuery, miniFiltersForType } = useValues(miniFiltersLogic)
    const { setSearchQuery, setMiniFilter, setMiniFilters } = useActions(miniFiltersLogic)
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const [focusedType, setFocusedType] = useState<FilterableInspectorListItemTypes | null>(null)

    const sharing = (logicProps.mode ?? SessionRecordingPlayerMode.Standard) === SessionRecordingPlayerMode.Sharing
    const itemCount = (type: FilterableInspectorListItemTypes): number => allItemsByItemType[type]?.length ?? 0

    const showDoctor =
        (!!window.IMPERSONATED_SESSION || !!featureFlags[FEATURE_FLAGS.SESSION_REPLAY_DOCTOR]) && !sharing
    const showLogs = !!featureFlags[FEATURE_FLAGS.SESSION_REPLAY_BACKEND_LOGS] && !sharing
    const showNetworkUpsell = !!currentTeam && itemCount('network') === 0 && !currentTeam.capture_performance_opt_in
    const showConsoleUpsell = !!currentTeam && itemCount('console') === 0 && !currentTeam.capture_console_log_opt_in
    const showLogsUpsell =
        showLogs && logsInitialLoadRequested && !logsLoading && !logsLoadError && itemCount('logs') === 0

    useEffect(() => {
        if (!window.IMPERSONATED_SESSION && !featureFlags[FEATURE_FLAGS.SESSION_REPLAY_DOCTOR]) {
            setMiniFilter('doctor', false)
        }
    }, [featureFlags, setMiniFilter])

    useEffect(() => {
        if (showNetworkUpsell) {
            posthog.capture('recording inspector upsell shown', { type: 'network' })
        }
    }, [showNetworkUpsell])
    useEffect(() => {
        if (showConsoleUpsell) {
            posthog.capture('recording inspector upsell shown', { type: 'console' })
        }
    }, [showConsoleUpsell])
    useEffect(() => {
        if (showLogsUpsell) {
            posthog.capture('recording inspector upsell shown', { type: 'logs' })
        }
    }, [showLogsUpsell])

    const types: InspectorFilterType[] = []
    if (!sharing) {
        types.push({
            type: 'events',
            label: 'Events',
            icon: <IconUnverifiedEvent />,
            dataAttr: 'player-inspector-events-toggle-all',
            disabledReason: itemCount('events') === 0 ? 'There are no events in this recording' : undefined,
        })
    }
    types.push(
        {
            type: 'console',
            label: 'Console',
            icon: <IconTerminal />,
            dataAttr: 'player-inspector-console-toggle-all',
            disabledReason: itemCount('console') === 0 ? 'There are no console logs in this recording' : undefined,
            setup: showConsoleUpsell
                ? {
                      label: 'Configure console log capture in settings',
                      to: urls.settings('project-replay', 'replay'),
                      dataAttr: 'player-inspector-console-upsell',
                  }
                : undefined,
        },
        {
            type: 'network',
            label: 'Network',
            icon: <IconDashboard />,
            dataAttr: 'player-inspector-network-toggle-all',
            disabledReason: itemCount('network') === 0 ? 'There are no network requests in this recording' : undefined,
            setup: showNetworkUpsell
                ? {
                      label: 'Configure network capture in settings',
                      to: urls.settings('project-replay', 'replay-network'),
                      dataAttr: 'player-inspector-network-upsell',
                  }
                : undefined,
        }
    )
    if (showLogs && !showLogsUpsell) {
        types.push({
            type: 'logs',
            label: 'Logs',
            icon: <IconLive />,
            dataAttr: 'player-inspector-logs-toggle-all',
            loading: logsLoading,
            disabledReason: logsAccessDenied
                ? "You don't have access to logs in this project"
                : logsLoading
                  ? 'Loading logs...'
                  : !logsInitialLoadRequested
                    ? "Logs load after the recording's events load"
                    : logsLoadError
                      ? 'Failed to load logs for this session'
                      : undefined,
        })
    }
    if (!sharing) {
        types.push({
            type: 'comment',
            label: 'Comments',
            icon: <IconComment />,
            dataAttr: 'player-inspector-comments-toggle',
            disabledReason: itemCount('comment') === 0 ? 'There are no comments in this recording' : undefined,
        })
    }
    if (showDoctor) {
        types.push({
            type: 'doctor',
            label: 'Doctor',
            icon: <IconStethoscope />,
            dataAttr: 'player-inspector-doctor-toggle',
            tooltip: 'Doctor events help diagnose the health of a recording, and are used by PostHog support',
        })
    }

    const subFiltersFor = (type: FilterableInspectorListItemTypes): ReturnType<typeof miniFiltersForType> =>
        miniFiltersForType(type)?.filter((x) => x.name !== 'All') ?? []
    const isEnabled = (type: FilterableInspectorListItemTypes): boolean => subFiltersFor(type).some((x) => !!x.enabled)
    const hasSubFilters = (type: FilterableInspectorListItemTypes): boolean =>
        subFiltersFor(type).length > 1 && itemCount(type) > 1

    const subFilterType =
        types.find((x) => x.type === focusedType)?.type ??
        types.find((x) => isEnabled(x.type) && hasSubFilters(x.type))?.type
    const subFilters = subFilterType && hasSubFilters(subFilterType) ? subFiltersFor(subFilterType) : []

    return (
        <div data-quill className="flex flex-col text-foreground">
            <div className="flex flex-wrap items-center gap-0.5 px-2 py-1 border-b border-border">
                {types.map(({ type, label, icon, dataAttr, tooltip, disabledReason, loading, setup }) => (
                    <span key={type} className="flex items-center">
                        <QuillInspectorToggle
                            pressed={isEnabled(type)}
                            onPressedChange={(pressed) => {
                                setMiniFilters(
                                    subFiltersFor(type).map((x) => x.key),
                                    pressed
                                )
                                setFocusedType(type)
                            }}
                            tooltip={tooltip}
                            disabledReason={disabledReason}
                            loading={loading}
                            data-attr={dataAttr}
                        >
                            {icon}
                            <span>{label}</span>
                            {itemCount(type) > 0 && (
                                <span className="tabular-nums text-muted-foreground" translate="no">
                                    {itemCount(type)}
                                </span>
                            )}
                        </QuillInspectorToggle>
                        {setup && (
                            <Button
                                size="icon-xs"
                                nativeButton={false}
                                render={<LinkPrimitive to={setup.to} />}
                                aria-label={setup.label}
                                tooltip={setup.label}
                                data-attr={setup.dataAttr}
                            >
                                <IconGear />
                            </Button>
                        )}
                    </span>
                ))}
                {showLogsUpsell && (
                    <Popover>
                        <PopoverTrigger
                            render={
                                <Button
                                    size="sm"
                                    className="text-muted-foreground"
                                    data-attr="player-inspector-logs-unavailable"
                                />
                            }
                        >
                            <IconLive />
                            Logs
                        </PopoverTrigger>
                        <PopoverContent align="end" className="w-auto p-0">
                            <SessionLogsUnavailableNotice sessionId={logicProps.sessionRecordingId} />
                        </PopoverContent>
                    </Popover>
                )}
            </div>

            {subFilters.length > 0 && (
                <div className="flex flex-wrap items-center gap-0.5 px-2 py-1 border-b border-border bg-muted">
                    {subFilters.map((filter) => (
                        <QuillInspectorToggle
                            key={filter.key}
                            pressed={!!filter.enabled}
                            onPressedChange={(pressed) => setMiniFilter(filter.key, pressed)}
                            tooltip={filter.tooltip}
                            data-attr={`player-inspector-${filter.key}-mini-filter-toggle`}
                        >
                            <span>{filter.name}</span>
                            <span className="tabular-nums text-muted-foreground" translate="no">
                                {allItemsByMiniFilterKey[filter.key]?.length ?? 0}
                            </span>
                        </QuillInspectorToggle>
                    ))}
                </div>
            )}

            <div className="flex px-2 py-1">
                <InputGroup size="sm" className="min-w-60">
                    <InputGroupInput
                        type="search"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        placeholder="Search..."
                        aria-label="Search the inspector"
                        data-attr="player-inspector-search-input"
                    />
                    <InputGroupAddon align="inline-end">
                        <InputGroupButton
                            size="icon-xs"
                            aria-label="How search works"
                            tooltip={<InspectorSearchInfo />}
                            data-attr="player-inspector-search-info"
                        >
                            <IconInfo />
                        </InputGroupButton>
                    </InputGroupAddon>
                </InputGroup>
            </div>
        </div>
    )
}
