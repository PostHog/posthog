import React from 'react'
import { Meta } from '@storybook/react'
import { Layout } from 'antd'
import { keaStory } from 'lib/storybook/kea-story'
import { MainNavigation } from '../navigation'

import { TopNavigation } from '../navigation/TopNavigation'

import navigationInitial from './navigation.initial.json'

export default {
    title: 'PostHog/Components/TopNavigation',
    parameters: {
        layout: 'fullscreen',
    },
} as Meta

export const PlainTopNavigation = keaStory(
    () => (
        <Layout>
            <MainNavigation />
            <Layout>
                <TopNavigation />
                {/* Normally here is the scene */}
            </Layout>
            {/* Normally here are essential elements */}
        </Layout>
    ),
    navigationInitial
)
