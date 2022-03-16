import React from 'react'
import { Meta } from '@storybook/react'
import { Layout } from 'antd'
import { TopBar } from '../TopBar/TopBar'
import { SideBar } from '../SideBar/SideBar'

export default {
    title: 'Layout/Navigation',
    parameters: {
        layout: 'fullscreen',
    },
} as Meta

export const Navigation = (): JSX.Element => (
    <Layout>
        <TopBar />
        <SideBar>
            <React.Fragment />
        </SideBar>
    </Layout>
)
