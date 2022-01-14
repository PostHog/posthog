import { Meta } from '@storybook/react'

import { keaStory } from 'lib/storybook/kea-story'

import { Insight } from '../Insight'

import retentionJson from './retention.json'
import lifecycleJson from './lifecycle.json'
import pathsJson from './paths.json'
import stickinessJson from './stickiness.json'

export default {
    title: 'PostHog/Scenes/Insights',
} as Meta

export const Retention = keaStory(Insight, retentionJson)
export const UserPaths = keaStory(Insight, pathsJson)
export const Stickiness = keaStory(Insight, stickinessJson)
export const Lifecycle = keaStory(Insight, lifecycleJson)
