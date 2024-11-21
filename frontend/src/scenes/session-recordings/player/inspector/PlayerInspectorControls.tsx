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
 * TODO only one window filter necessary!
 * TODO remove tab code entirely
 * TODO update tests
 * TODO how do we map existing "all" filters someone has set or just ignore
 * TODO show counts alongside selectors so folk know whether to click them
 */

export const TabToIcon = {
    [InspectorListItemType.EVENTS]: IconUnverifiedEvent,
    [InspectorListItemType.CONSOLE]: IconTerminal,
    [InspectorListItemType.NETWORK]: IconDashboard,
    [InspectorListItemType.DOCTOR]: IconBug,
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
        miniFiltersForType,
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
