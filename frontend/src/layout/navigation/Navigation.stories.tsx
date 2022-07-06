import React from 'react'
import { Meta } from '@storybook/react'
import { Layout } from 'antd'
import { TopBar } from './TopBar/TopBar'
import { SideBar } from './SideBar/SideBar'

export default {
    title: 'Layout/Navigation',
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'story' },
} as Meta

export function Navigation_(): JSX.Element {
    return (
        <Layout>
            <TopBar />
            <SideBar>
                <React.Fragment />
            </SideBar>
        </Layout>
    )
}
