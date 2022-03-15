import { Meta } from '@storybook/react'
import { keaStory } from 'storybook/kea-story'

import { IngestionWizard } from '../IngestionWizard'

import ingestionState from './ingestion.json'

export default {
    title: '___TO CLEAN/Onboarding/Ingestion',
} as Meta

export const Initial = keaStory(IngestionWizard, ingestionState)
