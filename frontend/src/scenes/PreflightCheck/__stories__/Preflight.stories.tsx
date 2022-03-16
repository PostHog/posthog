import { Meta } from '@storybook/react'
import { keaStory } from 'storybook/kea-story'

import { PreflightCheck } from '../index'

import preflightInitial from './preflight.initial.json'

export default {
    title: '___TO CLEAN/Onboarding/Preflight',
} as Meta

export const Initial = keaStory(PreflightCheck, preflightInitial)
