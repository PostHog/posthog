import { Menu } from '@base-ui/react/menu'
import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconChevronRight, IconClock, IconDatabase, IconPeople } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { urls } from 'scenes/urls'

import { ActivityTab } from '~/types'

import { iconForType } from '../ProjectTree/defaultTree'
import { panelLayoutLogic } from '../panelLayoutLogic'

export function DataMenu(): JSX.Element {
    const { isLayoutNavCollapsed } = useValues(panelLayoutLogic)

    return (
        <Menu.Root>
            <Menu.Trigger
                render={
                    <ButtonPrimitive
                        iconOnly={isLayoutNavCollapsed}
                        menuItem={!isLayoutNavCollapsed}
                        className="hidden lg:flex"
                    >
                        <IconDatabase className="size-4 text-secondary" />
                        {!isLayoutNavCollapsed && (
                            <>
                                <span className="flex-1 text-left">Data</span>
                                <IconChevronRight className="size-3 text-secondary" />
                            </>
                        )}
                    </ButtonPrimitive>
                }
            />
            <Menu.Portal>
                <Menu.Positioner
                    className="z-[var(--z-popover)]"
                    side="right"
                    align="start"
                    sideOffset={6}
                    alignOffset={-4}
                >
                    <Menu.Popup className="primitive-menu-content flex flex-col gap-px p-1">
                        <Menu.Item
                            onClick={() => router.actions.push(urls.activity(ActivityTab.ExploreEvents))}
                            render={
                                <ButtonPrimitive
                                    iconOnly={isLayoutNavCollapsed}
                                    menuItem={!isLayoutNavCollapsed}
                                    className="hidden lg:flex"
                                >
                                    <IconClock className="size-4 text-secondary" />
                                    Activity
                                </ButtonPrimitive>
                            }
                        />
                        <Menu.Item
                            onClick={() => router.actions.push(urls.persons())}
                            render={
                                <ButtonPrimitive
                                    iconOnly={isLayoutNavCollapsed}
                                    menuItem={!isLayoutNavCollapsed}
                                    className="hidden lg:flex"
                                >
                                    <IconPeople className="size-4 text-secondary" />
                                    Persons
                                </ButtonPrimitive>
                            }
                        />

                        {/* Data management submenu */}
                        <Menu.SubmenuRoot>
                            <Menu.SubmenuTrigger
                                render={
                                    <ButtonPrimitive
                                        iconOnly={isLayoutNavCollapsed}
                                        menuItem={!isLayoutNavCollapsed}
                                        className="hidden lg:flex"
                                    >
                                        {iconForType('data_warehouse')}
                                        <span className="flex-1">Data management</span>
                                        <IconChevronRight className="size-3 text-secondary" />
                                    </ButtonPrimitive>
                                }
                            />
                            <Menu.Portal>
                                <Menu.Positioner className="z-[var(--z-popover)]" alignOffset={-4}>
                                    <Menu.Popup className="primitive-menu-content flex flex-col gap-px p-1">
                                        <Menu.Item
                                            onClick={() => router.actions.push(urls.eventDefinitions())}
                                            render={
                                                <ButtonPrimitive menuItem>
                                                    {iconForType('event_definition')}
                                                    Events
                                                </ButtonPrimitive>
                                            }
                                        />
                                        <Menu.Item
                                            onClick={() => router.actions.push(urls.propertyDefinitions())}
                                            render={
                                                <ButtonPrimitive
                                                    iconOnly={isLayoutNavCollapsed}
                                                    menuItem={!isLayoutNavCollapsed}
                                                    className="hidden lg:flex"
                                                >
                                                    {iconForType('property_definition')}
                                                    Properties
                                                </ButtonPrimitive>
                                            }
                                        />
                                        <Menu.Item
                                            onClick={() => router.actions.push(urls.annotations())}
                                            render={
                                                <ButtonPrimitive
                                                    iconOnly={isLayoutNavCollapsed}
                                                    menuItem={!isLayoutNavCollapsed}
                                                    className="hidden lg:flex"
                                                >
                                                    {iconForType('annotation')}
                                                    Annotations
                                                </ButtonPrimitive>
                                            }
                                        />
                                        <Menu.Item
                                            onClick={() => router.actions.push(urls.dataManagementHistory())}
                                            render={
                                                <ButtonPrimitive
                                                    iconOnly={isLayoutNavCollapsed}
                                                    menuItem={!isLayoutNavCollapsed}
                                                    className="hidden lg:flex"
                                                >
                                                    {iconForType('annotation')}
                                                    History
                                                </ButtonPrimitive>
                                            }
                                        />
                                    </Menu.Popup>
                                </Menu.Positioner>
                            </Menu.Portal>
                        </Menu.SubmenuRoot>

                        <Menu.Item
                            onClick={() => router.actions.push(urls.groups(0))}
                            render={
                                <ButtonPrimitive
                                    iconOnly={isLayoutNavCollapsed}
                                    menuItem={!isLayoutNavCollapsed}
                                    className="hidden lg:flex"
                                >
                                    {iconForType('group')}
                                    Groups
                                </ButtonPrimitive>
                            }
                        />
                    </Menu.Popup>
                </Menu.Positioner>
            </Menu.Portal>
        </Menu.Root>
    )
}
