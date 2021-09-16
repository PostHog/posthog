import { Meta } from '@storybook/react'
import { keaStory } from 'lib/storybook/kea-story'

import { SavedInsights } from '../SavedInsights'

import savedInsightsListState from './saved-insights-list.json'
import savedInsightsCardState from './saved-insights-card.json'

export default {
    title: 'PostHog/Scenes/SavedInsights',
} as Meta

export const AllInsightsList = keaStory(SavedInsights, savedInsightsListState)
export const AllInsightsCard = keaStory(SavedInsights, savedInsightsCardState)
