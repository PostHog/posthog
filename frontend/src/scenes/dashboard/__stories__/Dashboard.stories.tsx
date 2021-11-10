import React from 'react'
import { Meta } from '@storybook/react'
import { keaStory } from 'lib/storybook/kea-story'

import { Dashboard } from '../Dashboard'

import dashboardState from './dashboard.json'

export default {
    title: 'PostHog/Scenes/Dashboard',
} as Meta

export const AllPossibleInsightTypes = keaStory(function DashboardInner() {
    return <Dashboard id={dashboardState.scenes.dashboard.dashboardLogic['1'].allItems.id.toString()} />
}, dashboardState)
