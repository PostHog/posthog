import { Meta } from '@storybook/react'

import { keaStory } from 'lib/storybook/kea-story'

import { Insights } from '../Insights'

import trendsJson from './trends.json'
import retentionJson from './retention.json'
import lifecycleJson from './lifecycle.json'
import pathsJson from './paths.json'
import sessionsJson from './sessions.json'
import stickinessJson from './stickiness.json'

export default {
    title: 'PostHog/Scenes/Insights',
} as Meta

export const Trends = keaStory(Insights, trendsJson)
export const Retention = keaStory(Insights, retentionJson)
export const UserPaths = keaStory(Insights, pathsJson)
export const Sessions = keaStory(Insights, sessionsJson)
export const Stickiness = keaStory(Insights, stickinessJson)
export const Lifecycle = keaStory(Insights, lifecycleJson)
