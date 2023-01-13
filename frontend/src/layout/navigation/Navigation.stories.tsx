import { Meta } from '@storybook/react'
import { TopBar } from './TopBar/TopBar'
import { SideBar } from './SideBar/SideBar'
import React from 'react'

export default {
    title: 'Layout/Navigation',
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'story' },
} as Meta

export function Navigation_(): JSX.Element {
    return (
        <div>
            <TopBar />
            <SideBar>
                <React.Fragment />
            </SideBar>
        </div>
    )
}
