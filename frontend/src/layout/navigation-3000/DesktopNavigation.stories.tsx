import type { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { DesktopNavigation } from './DesktopNavigation'

function NavigationSidebar({ collapsed }: { collapsed: boolean }): JSX.Element {
    const { toggleLayoutNavCollapsed } = useActions(panelLayoutLogic)
    useOnMountEffect(() => toggleLayoutNavCollapsed(collapsed))

    return (
        <div className={`bg-surface-tertiary border rounded ${collapsed ? 'w-12' : 'w-[216px]'}`}>
            <DesktopNavigation />
        </div>
    )
}

const meta: Meta<typeof NavigationSidebar> = {
    title: 'Layout/Desktop navigation',
    component: NavigationSidebar,
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        pageUrl: '/project/1/home',
    },
    args: { collapsed: false },
}

export default meta

export const Library: StoryObj<typeof NavigationSidebar> = {}
export const Collapsed: StoryObj<typeof NavigationSidebar> = { args: { collapsed: true } }
