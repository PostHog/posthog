import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { BaseIcon, IconCheck, IconChevronDown, IconEye, IconHide, IconLogomark, IconVideoCamera } from '@posthog/icons'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { SimpleKeyValueList } from 'lib/components/SimpleKeyValueList'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { dayjs } from 'lib/dayjs'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonMenuItem } from 'lib/lemon-ui/LemonMenu'
import { IconUnverifiedEvent } from 'lib/lemon-ui/icons'
import { SettingsBar, SettingsMenu } from 'scenes/session-recordings/components/PanelSettings'

import { eventDebugMenuLogic } from '~/toolbar/debug/eventDebugMenuLogic'
import { EventType } from '~/types'

import { ToolbarMenu } from '../bar/ToolbarMenu'

function checkableMenuItem(
    label: string,
    count: number | null,
    icon: JSX.Element | null,
    isActive: boolean,
    onClick: () => void
): LemonMenuItem {
    return {
        label: (
            <div className="w-full flex flex-row justify-between items-center">
                <div className="flex flex-row items-center gap-1">
                    {isActive ? <IconCheck /> : <BaseIcon />}
                    {icon}
                    {label}
                </div>
                {count !== null && (
                    <span
                        // without setting fontVariant to none a single digit number between brackets gets rendered as a ligature 🤷
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ fontVariant: 'none' }}
                    >
                        ({count})
                    </span>
                )}
            </div>
        ),
        active: isActive,
        onClick: onClick,
    }
}

function EventTimestamp({ e }: { e: EventType }): JSX.Element {
    const ts = dayjs(e.timestamp)

    let formatString = 'HH:mm:ss'
    // if we're watching events around midnight, show the day as well for yesterday's events
    if (!ts.isSame(dayjs(), 'day')) {
        formatString = 'ddd HH:mm:ss'
    }

    return (
        <div>
            <span>{ts.format(formatString)}</span>
            <span className="text-xxs text-secondary">{ts.format('.SSS')}</span>
        </div>
    )
}

export const EventDebugMenu = (): JSX.Element => {
    const {
        searchText,
        isCollapsedEventRow,
        activeFilteredEvents,
        searchFilteredEventsCount,
        selectedEventTypes,
        hidePostHogProperties,
        hidePostHogFlags,
        expandedProperties,
    } = useValues(eventDebugMenuLogic)
    const { markExpanded, setSelectedEventType, setSearchText, setHidePostHogProperties, setHidePostHogFlags } =
        useActions(eventDebugMenuLogic)

    const showEventsMenuItems = [
        checkableMenuItem(
            'PostHog Events',
            searchFilteredEventsCount['posthog'],
            <IconLogomark />,
            selectedEventTypes.includes('posthog'),
            () => setSelectedEventType('posthog', !selectedEventTypes.includes('posthog'))
        ),
        checkableMenuItem(
            'Custom Events',
            searchFilteredEventsCount['custom'],
            <IconVideoCamera />,
            selectedEventTypes.includes('custom'),
            () => setSelectedEventType('custom', !selectedEventTypes.includes('custom'))
        ),
        checkableMenuItem(
            'Replay Events',
            searchFilteredEventsCount['snapshot'],
            <IconUnverifiedEvent />,
            selectedEventTypes.includes('snapshot'),
            () => setSelectedEventType('snapshot', !selectedEventTypes.includes('snapshot'))
        ),
    ]

    const hideThingsMenuItems = [
        checkableMenuItem('Hide PostHog properties', null, null, hidePostHogProperties, () =>
            setHidePostHogProperties(!hidePostHogProperties)
        ),
        checkableMenuItem('Hide PostHog flags', null, null, hidePostHogFlags, () =>
            setHidePostHogFlags(!hidePostHogFlags)
        ),
    ]

    return (
        <ToolbarMenu>
            <ToolbarMenu.Header>
                <div className="flex flex-col pb-2 deprecated-space-y-1">
                    <div className="flex justify-center flex-col">
                        <LemonInput
                            autoFocus={true}
                            fullWidth={true}
                            placeholder="Search"
                            type="search"
                            value={searchText}
                            onChange={setSearchText}
                        />
                    </div>
                </div>
            </ToolbarMenu.Header>
            <ToolbarMenu.Body>
                <div className="flex flex-col deprecated-space-y-1">
                    <div className="flex-1 text-sm pl-1">
                        View all events sent from this page as they are sent to PostHog.
                    </div>
                    {activeFilteredEvents.length ? (
                        activeFilteredEvents.map((e) => {
                            const expanded = e.uuid !== undefined && !isCollapsedEventRow(e.uuid)

                            return (
                                <div
                                    className="-mx-1 py-1 px-2 cursor-pointer"
                                    key={e.uuid}
                                    onClick={() => {
                                        expanded ? markExpanded(null) : markExpanded(e.uuid || null)
                                    }}
                                >
                                    <div className="flex flex-row justify-between hover:bg-surface-primary hover:text-accent-highlight">
                                        <EventTimestamp e={e} />

                                        <div className="flex flex-row items-end gap-1">
                                            <PropertyKeyInfo
                                                disableIcon
                                                value={e.event}
                                                type={TaxonomicFilterGroupType.Events}
                                            />
                                            <IconChevronDown className={clsx(expanded ? 'rotate-180' : '')} />
                                        </div>
                                    </div>
                                    {expanded && (
                                        <div className="my-1 ml-1 pl-2 border-l-2">
                                            <SimpleKeyValueList
                                                item={expandedProperties}
                                                emptyMessage={searchText ? 'No matching properties' : 'No properties'}
                                            />
                                        </div>
                                    )}
                                </div>
                            )
                        })
                    ) : (
                        <div className="px-4 py-2">
                            {searchText && !!activeFilteredEvents.length
                                ? 'Nothing matches your search.'
                                : 'Interact with your page and then come back to the toolbar to see what events were generated.'}
                        </div>
                    )}
                </div>
            </ToolbarMenu.Body>
            <ToolbarMenu.Footer>
                <SettingsBar border="none" className="justify-between">
                    <SettingsMenu
                        items={hideThingsMenuItems}
                        highlightWhenActive={false}
                        icon={<IconHide />}
                        label="Hide properties"
                    />
                    <SettingsMenu
                        items={showEventsMenuItems}
                        highlightWhenActive={false}
                        icon={<IconEye />}
                        label={`Showing ${activeFilteredEvents.length} events`}
                    />
                </SettingsBar>
            </ToolbarMenu.Footer>
        </ToolbarMenu>
    )
}
