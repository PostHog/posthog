import { Meta } from '@storybook/react'
import { keaStory } from 'lib/storybook/kea-story'

import { Signup } from '../Signup'

import signupJson from './signup.json'

export default {
    title: 'PostHog/Onboarding/2 Signup',
} as Meta

export const Initial = keaStory(Signup, signupJson)
