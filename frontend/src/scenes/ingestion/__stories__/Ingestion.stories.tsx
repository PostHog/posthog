import { Meta } from '@storybook/react'
import { keaStory } from 'lib/storybook/kea-story'

import { IngestionWizard } from '../IngestionWizard'

import ingestionState from './ingestion.json'

export default {
    title: 'Scenes/Onboarding/Ingestion',
} as Meta

export const Initial = keaStory(IngestionWizard, ingestionState)
