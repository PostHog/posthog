import { BaseIcon, IconBug, IconCheck, IconDashboard, IconInfo, IconSearch, IconTerminal } from '@posthog/icons'
import { LemonButton, LemonButtonProps, LemonInput, LemonMenu, LemonMenuItem, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconUnverifiedEvent } from 'lib/lemon-ui/icons'
import { LemonMenuProps } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { useEffect, useState } from 'react'
import { miniFiltersLogic, SharedListMiniFilter } from 'scenes/session-recordings/player/inspector/miniFiltersLogic'
import { playerInspectorLogic } from 'scenes/session-recordings/player/inspector/playerInspectorLogic'

import { InspectorListItemType } from '~/types'

import { sessionRecordingPlayerLogic, SessionRecordingPlayerMode } from '../sessionRecordingPlayerLogic'
import { InspectorSearchInfo } from './components/InspectorSearchInfo'

export const TabToIcon = {
    [InspectorListItemType.EVENTS]: IconUnverifiedEvent,
    [InspectorListItemType.CONSOLE]: IconTerminal,
    [InspectorListItemType.NETWORK]: IconDashboard,
    [InspectorListItemType.DOCTOR]: IconBug,
}

function SettingsMenu({
    label,
    items,
    icon,
    ...props
}: Omit<LemonMenuProps, 'items' | 'children'> & {
    items: LemonMenuItem[]
    label: JSX.Element | string
    icon: JSX.Element
}): JSX.Element {
    return (
        <LemonMenu buttonSize="xsmall" closeOnClickInside={false} items={items} {...props}>
            <LemonButton status={items.some((cf) => !!cf.active) ? 'danger' : 'default'} size="xsmall" icon={icon}>
                {label}
            </LemonButton>
        </LemonMenu>
    )
}

export function SettingsToggle({
    title,
    icon,
    label,
    active,
    ...props
}: Omit<LemonButtonProps, 'status' | 'sideAction'> & {
    active: boolean
    title: string
    icon?: JSX.Element | null
    label: JSX.Element | string
}): JSX.Element {
    return (
        <Tooltip title={title}>
            <LemonButton icon={icon} size="xsmall" status={active ? 'danger' : 'default'} {...props}>
                {label}
            </LemonButton>
        </Tooltip>
    )
}

export function PlayerInspectorControls(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { allItemsByMiniFilterKey } = useValues(playerInspectorLogic(logicProps))
    const { searchQuery, miniFiltersForType, miniFiltersByKey } = useValues(miniFiltersLogic)
    const { setSearchQuery, setMiniFilter } = useActions(miniFiltersLogic)

    const mode = logicProps.mode ?? SessionRecordingPlayerMode.Standard

    const { featureFlags } = useValues(featureFlagLogic)

    const [showSearch, setShowSearch] = useState(false)

    useEffect(() => {
        if (!window.IMPERSONATED_SESSION && !featureFlags[FEATURE_FLAGS.SESSION_REPLAY_DOCTOR]) {
            // ensure we've not left the doctor active
            setMiniFilter('doctor', false)
        }
    }, [])

    function filterMenuForType(type: InspectorListItemType): LemonMenuItem[] {
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

    const eventsFilters: LemonMenuItem[] = filterMenuForType(InspectorListItemType.EVENTS)
    const consoleFilters: LemonMenuItem[] = filterMenuForType(InspectorListItemType.CONSOLE)
    const networkFilters: LemonMenuItem[] = filterMenuForType(InspectorListItemType.NETWORK)

    return (
        <div className="bg-bg-3000 border-b">
            <div className="flex flex-nowrap">
                <div className="flex flex-1 border-b shrink-0 mr-2 items-center justify-end font-light">
                    {mode !== SessionRecordingPlayerMode.Sharing && (
                        <SettingsMenu
                            items={eventsFilters}
                            label={capitalizeFirstLetter(InspectorListItemType.EVENTS)}
                            icon={<IconUnverifiedEvent />}
                        />
                    )}
                    <SettingsMenu
                        items={consoleFilters}
                        label={capitalizeFirstLetter(InspectorListItemType.CONSOLE)}
                        icon={<IconTerminal />}
                    />
                    <SettingsMenu
                        items={networkFilters}
                        label={capitalizeFirstLetter(InspectorListItemType.NETWORK)}
                        icon={<IconDashboard />}
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
