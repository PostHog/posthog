import React from 'react'
import { Meta } from '@storybook/react'
import { Layout } from 'antd'
import { keaStory } from 'lib/storybook/kea-story'
import lemonadeInitial from './lemonade.initial.json'
import { TopBar } from '../TopBar'

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
        </Layout>
    ),
    lemonadeInitial
)
