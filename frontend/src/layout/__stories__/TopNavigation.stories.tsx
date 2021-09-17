import { Meta } from '@storybook/react'
import { keaStory } from 'lib/storybook/kea-story'

import { TopNavigation } from '../navigation/TopNavigation'

import topNavigationInitial from './topNavigation.initial.json'

export default {
    title: 'PostHog/Components/TopNavigation',
} as Meta

export const PlainTopNavigation = keaStory(TopNavigation, topNavigationInitial)
