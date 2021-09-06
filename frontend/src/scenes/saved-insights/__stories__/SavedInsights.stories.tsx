import React from 'react'
import { ComponentMeta } from '@storybook/react'
import { KeaStory } from 'lib/storybook/kea-story'

import { SavedInsights } from '../SavedInsights'

import savedInsightsListState from './saved-insights-list.json'
import savedInsightsCardState from './saved-insights-card.json'

export default {
    title: 'PostHog/Scenes/SavedInsights',
    component: SavedInsights,
} as ComponentMeta<typeof SavedInsights>

export const AllInsightsList = (): JSX.Element => (
    <KeaStory state={savedInsightsListState}>
        <SavedInsights />
    </KeaStory>
)

export const AllInsightsCard = (): JSX.Element => (
    <KeaStory state={savedInsightsCardState}>
        <SavedInsights />
    </KeaStory>
)
