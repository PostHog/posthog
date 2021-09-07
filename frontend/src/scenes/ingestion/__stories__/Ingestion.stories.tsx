import React from 'react'
import { ComponentMeta } from '@storybook/react'
import { KeaStory } from 'lib/storybook/kea-story'

import { IngestionWizard } from '../IngestionWizard'

import ingestionState from './ingestion.json'

export default {
    title: 'PostHog/Onboarding/3 Ingestion',
    component: IngestionWizard,
} as ComponentMeta<typeof IngestionWizard>

export const Initial = (): JSX.Element => (
    <KeaStory state={ingestionState}>
        <IngestionWizard />
    </KeaStory>
)
