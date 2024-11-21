import { BaseIcon, IconBug, IconCheck, IconDashboard, IconInfo, IconSearch, IconTerminal } from '@posthog/icons'
import { LemonButton, LemonInput, LemonMenu, LemonMenuItem, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconUnverifiedEvent } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { useState } from 'react'
import { miniFiltersLogic, SharedListMiniFilter } from 'scenes/session-recordings/player/inspector/miniFiltersLogic'

import { InspectorListItemType } from '~/types'

import { sessionRecordingPlayerLogic, SessionRecordingPlayerMode } from '../sessionRecordingPlayerLogic'
import { InspectorSearchInfo } from './components/InspectorSearchInfo'

/**
 * TODO how do we map existing "all" filters someone has set or just ignore
 * TODO show counts alongside selectors so folk know whether to click them
 */

export const TabToIcon = {
    [InspectorListItemType.EVENTS]: IconUnverifiedEvent,
    [InspectorListItemType.CONSOLE]: IconTerminal,
    [InspectorListItemType.NETWORK]: IconDashboard,
    [InspectorListItemType.DOCTOR]: IconBug,
}

export function PlayerInspectorControls(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { searchQuery, miniFiltersForType, miniFiltersByKey } = useValues(miniFiltersLogic)
    const { setSearchQuery, setMiniFilter } = useActions(miniFiltersLogic)

    const mode = logicProps.mode ?? SessionRecordingPlayerMode.Standard

    const { featureFlags } = useValues(featureFlagLogic)

    const [showSearch, setShowSearch] = useState(false)

    if (!window.IMPERSONATED_SESSION && !featureFlags[FEATURE_FLAGS.SESSION_REPLAY_DOCTOR]) {
        // ensure we've not left the doctor active
        setMiniFilter('doctor', false)
    }

    const eventsFilters: LemonMenuItem[] = miniFiltersForType(InspectorListItemType.EVENTS)
        ?.filter((x) => x.name !== 'All')
        .map(
            (filter: SharedListMiniFilter) =>
                ({
                    label: filter.name,
                    icon: filter.enabled ? <IconCheck className="text-sm" /> : <BaseIcon className="text-sm" />,
                    status: filter.enabled ? 'danger' : 'default',
                    onClick: () => {
                        setMiniFilter(filter.key, !filter.enabled)
                    },
                    tooltip: filter.tooltip,
                    active: filter.enabled,
                } satisfies LemonMenuItem)
        )

    const consoleFilters: LemonMenuItem[] = miniFiltersForType(InspectorListItemType.CONSOLE)
        ?.filter((x) => x.name !== 'All')
        .map(
            (filter: SharedListMiniFilter) =>
                ({
                    label: filter.name,
                    icon: filter.enabled ? <IconCheck className="text-sm" /> : <BaseIcon className="text-sm" />,
                    status: filter.enabled ? 'danger' : 'default',
                    onClick: () => {
                        setMiniFilter(filter.key, !filter.enabled)
                    },
                    tooltip: filter.tooltip,
                    active: filter.enabled,
                } satisfies LemonMenuItem)
        )

    const networkFilters: LemonMenuItem[] = miniFiltersForType(InspectorListItemType.NETWORK)
        ?.filter((x) => x.name !== 'All')
        .map(
            (filter: SharedListMiniFilter) =>
                ({
                    label: filter.name,
                    icon: filter.enabled ? <IconCheck className="text-sm" /> : <BaseIcon className="text-sm" />,
                    status: filter.enabled ? 'danger' : 'default',
                    onClick: () => {
                        setMiniFilter(filter.key, !filter.enabled)
                    },
                    tooltip: filter.tooltip,
                    active: filter.enabled,
                } satisfies LemonMenuItem)
        )

    return (
        <div className="bg-bg-3000 border-b">
            <div className="flex flex-nowrap">
                <div className="flex flex-1 border-b shrink-0 mr-2 items-center justify-end font-light">
                    {mode !== SessionRecordingPlayerMode.Sharing && (
                        <LemonMenu buttonSize="xsmall" closeOnClickInside={false} items={eventsFilters}>
                            <LemonButton
                                status={eventsFilters.some((cf) => !!cf.active) ? 'danger' : 'default'}
                                size="xsmall"
                                icon={<IconUnverifiedEvent />}
                            >
                                {capitalizeFirstLetter(InspectorListItemType.EVENTS)}
                            </LemonButton>
                        </LemonMenu>
                    )}
                    <LemonMenu buttonSize="xsmall" closeOnClickInside={false} items={consoleFilters}>
                        <LemonButton
                            status={consoleFilters.some((cf) => !!cf.active) ? 'danger' : 'default'}
                            size="xsmall"
                            icon={<IconTerminal />}
                        >
                            {capitalizeFirstLetter(InspectorListItemType.CONSOLE)}
                        </LemonButton>
                    </LemonMenu>
                    <LemonMenu buttonSize="xsmall" closeOnClickInside={false} items={networkFilters}>
                        <LemonButton
                            status={networkFilters.some((cf) => !!cf.active) ? 'danger' : 'default'}
                            size="xsmall"
                            icon={<IconDashboard />}
                        >
                            {capitalizeFirstLetter(InspectorListItemType.NETWORK)}
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
