import React from 'react'

import { ProfileBubbles as ProfileBubblesComponent, ProfileBubblesProps } from './ProfileBubbles'
import { ComponentMeta } from '@storybook/react'

const DUMMIES: ProfileBubblesProps['people'] = [
    { email: 'michael@posthog.com', name: 'Michael' },
    { email: 'lottie@posthog.com', name: 'Lottie' },
    { email: 'paul@posthog.com', name: 'Paul' },
    { email: 'joe@posthog.com', name: 'Joe' },
]

export default {
    title: 'Lemon UI/Profile Bubbles',
    component: ProfileBubblesComponent,
    argTypes: {
        people: {
            defaultValue: DUMMIES,
        },
    },
} as ComponentMeta<typeof ProfileBubblesComponent>

export function OneBubble(props: any): JSX.Element {
    return <ProfileBubblesComponent {...props} people={DUMMIES.slice(0, 1)} />
}

export function MultipleBubblesWithTooltip(props: any): JSX.Element {
    return <ProfileBubblesComponent {...props} tooltip="Cool people." />
}

export function MultipleBubblesAtLimit(props: any): JSX.Element {
    return <ProfileBubblesComponent {...props} limit={4} />
}

export function MultipleBubblesOverflowingByOne(props: any): JSX.Element {
    return <ProfileBubblesComponent {...props} limit={3} />
}

export function MultipleBubblesOverflowingByTwo(props: any): JSX.Element {
    return <ProfileBubblesComponent {...props} limit={2} />
}
