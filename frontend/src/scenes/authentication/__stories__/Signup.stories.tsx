import React from 'react'
import { ComponentMeta } from '@storybook/react'
import { KeaStory } from 'lib/storybook/kea-story'

import { Signup } from '../Signup'

import signup from './signup.json'

export default {
    title: 'PostHog/Onboarding/2 Signup',
    component: Signup,
} as ComponentMeta<typeof Signup>

export const Initial = (): JSX.Element => (
    <KeaStory state={signup}>
        <Signup />
    </KeaStory>
)
