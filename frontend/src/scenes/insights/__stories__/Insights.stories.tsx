import React from 'react'
import { ComponentMeta } from '@storybook/react'
import { KeaStory } from 'lib/storybook/kea-story'

import { Insights } from '../Insights'

import trendsState from './trends.json'
import funnelsState from './funnels.json'
import retentionState from './retention.json'
import lifecycleState from './lifecycle.json'
import pathsState from './paths.json'
import sessionsState from './sessions.json'
import stickinessState from './stickiness.json'

export default {
    title: 'PostHog/Scenes/Insights',
    component: Insights,
} as ComponentMeta<typeof Insights>

export const Trends = (): JSX.Element => (
    <KeaStory state={trendsState}>
        <Insights />
    </KeaStory>
)

export const Funnels = (): JSX.Element => (
    <KeaStory state={funnelsState}>
        <Insights />
    </KeaStory>
)

export const Retention = (): JSX.Element => (
    <KeaStory state={retentionState}>
        <Insights />
    </KeaStory>
)

export const UserPaths = (): JSX.Element => (
    <KeaStory state={pathsState}>
        <Insights />
    </KeaStory>
)

export const Sessions = (): JSX.Element => (
    <KeaStory state={sessionsState}>
        <Insights />
    </KeaStory>
)

export const Stickiness = (): JSX.Element => (
    <KeaStory state={stickinessState}>
        <Insights />
    </KeaStory>
)

export const Lifecycle = (): JSX.Element => (
    <KeaStory state={lifecycleState}>
        <Insights />
    </KeaStory>
)
