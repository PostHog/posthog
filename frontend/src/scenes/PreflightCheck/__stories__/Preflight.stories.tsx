import { Meta } from '@storybook/react'
import { keaStory } from 'lib/storybook/kea-story'

import { PreflightCheck } from '../index'

import preflightInitial from './preflight.initial.json'

export default {
    title: 'PostHog/Onboarding/1 Preflight',
} as Meta

export const Initial = keaStory(PreflightCheck, preflightInitial)
