import React from 'react'
import { ComponentMeta } from '@storybook/react'
import { KeaStory } from 'lib/storybook/kea-story'

import { PreflightCheck } from '../index'

import preflightInitial from './preflight.initial.json'

export default {
    title: 'PostHog/Onboarding/1 Preflight',
    component: PreflightCheck,
} as ComponentMeta<typeof PreflightCheck>

export const Initial = (): JSX.Element => (
    <KeaStory state={preflightInitial}>
        <PreflightCheck />
    </KeaStory>
)
