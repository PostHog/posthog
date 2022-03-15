import { Meta } from '@storybook/react'

import { keaStory } from 'storybook/kea-story'

import { InsightScene } from '../InsightScene'

import retentionJson from './retention.json'
import lifecycleJson from './lifecycle.json'
import pathsJson from './paths.json'
import stickinessJson from './stickiness.json'

export default {
    title: 'Scenes/Insights',
} as Meta

export const Retention = keaStory(InsightScene, retentionJson)
export const UserPaths = keaStory(InsightScene, pathsJson)
export const Stickiness = keaStory(InsightScene, stickinessJson)
export const Lifecycle = keaStory(InsightScene, lifecycleJson)
