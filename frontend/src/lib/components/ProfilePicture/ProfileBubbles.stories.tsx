import React from 'react'
import { ComponentMeta } from '@storybook/react'

import { ProfileBubbles as ProfileBubblesComponent, ProfileBubblesProps } from './ProfileBubbles'

export default {
    title: 'PostHog/Components/ProfileBubbles',
    component: ProfileBubblesComponent,
    parameters: {
        layout: 'centered',
    },
} as ComponentMeta<typeof ProfileBubblesComponent>

const DUMMIES: ProfileBubblesProps['people'] = [
    { email: 'michael@posthog.com', name: 'Michael' },
    { email: 'lottie@posthog.com', name: 'Lottie' },
    { email: 'paul@posthog.com', name: 'Paul' },
    { email: 'joe@posthog.com', name: 'Joe' },
]

export function OneBubble(): JSX.Element {
    return <ProfileBubblesComponent people={DUMMIES.slice(0, 1)} />
}

export function MultipleBubblesWithTooltip(): JSX.Element {
    return <ProfileBubblesComponent people={DUMMIES} tooltip="Cool people." />
}

export function MultipleBubblesAtLimit(): JSX.Element {
    return <ProfileBubblesComponent people={DUMMIES} limit={4} />
}

export function MultipleBubblesOverflowingByOne(): JSX.Element {
    return <ProfileBubblesComponent people={DUMMIES} limit={3} />
}

export function MultipleBubblesOverflowingByTwo(): JSX.Element {
    return <ProfileBubblesComponent people={DUMMIES} limit={2} />
}
