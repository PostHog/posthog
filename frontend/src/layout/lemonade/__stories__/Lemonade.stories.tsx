import React from 'react'
import { Meta } from '@storybook/react'
import { Layout } from 'antd'
import { keaStory } from 'lib/storybook/kea-story'
import lemonadeInitial from './lemonade.initial.json'
import { TopBar } from '../TopBar'
import { SideBar } from '../SideBar/SideBar'

export default {
    title: 'PostHog/Lemonade',
    parameters: {
        layout: 'fullscreen',
    },
} as Meta

export const Lemonade = keaStory(
    () => (
        <Layout>
            <TopBar />
            <SideBar>
                <React.Fragment />
            </SideBar>
        </Layout>
    ),
    lemonadeInitial
)
