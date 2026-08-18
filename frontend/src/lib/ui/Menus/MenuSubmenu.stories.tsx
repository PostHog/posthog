import { Menu } from '@base-ui/react/menu'
import type { Meta } from '@storybook/react'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { MenuOpenIndicator } from './Menus'
import { MenuSubmenu } from './MenuSubmenu'

const meta = {
    title: 'UI/MenuSubmenu',
    component: MenuSubmenu,
    tags: ['autodocs'],
} satisfies Meta<typeof MenuSubmenu>

export default meta

export function Default(): JSX.Element {
    return (
        <Menu.Root>
            <Menu.Trigger
                render={<ButtonPrimitive data-attr="menu-submenu-story-trigger">Open menu</ButtonPrimitive>}
            />
            <Menu.Portal>
                <Menu.Positioner className="z-[var(--z-popover)]">
                    <Menu.Popup className="primitive-menu-content min-w-[200px]">
                        <div className="primitive-menu-content-inner flex flex-col gap-px p-1">
                            <Menu.Item render={<ButtonPrimitive menuItem>Plain item</ButtonPrimitive>} />
                            <MenuSubmenu
                                popupClassName="min-w-[200px]"
                                trigger={
                                    <ButtonPrimitive menuItem data-attr="menu-submenu-story-submenu-trigger">
                                        Submenu on hover
                                        <MenuOpenIndicator intent="sub" className="ml-auto" />
                                    </ButtonPrimitive>
                                }
                            >
                                <div className="primitive-menu-content-inner flex flex-col gap-px p-1">
                                    <Menu.Item render={<ButtonPrimitive menuItem>First</ButtonPrimitive>} />
                                    <Menu.Item render={<ButtonPrimitive menuItem>Second</ButtonPrimitive>} />
                                    <Menu.Item render={<ButtonPrimitive menuItem>Third</ButtonPrimitive>} />
                                </div>
                            </MenuSubmenu>
                        </div>
                    </Menu.Popup>
                </Menu.Positioner>
            </Menu.Portal>
        </Menu.Root>
    )
}
