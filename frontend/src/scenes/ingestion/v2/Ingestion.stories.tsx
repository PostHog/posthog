import { Meta } from '@storybook/react'

import { IngestionWizardV2 } from './IngestionWizard'

export default {
    title: 'Scenes-Other/Onboarding',
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'story' },
} as Meta

export const Ingestion = (): JSX.Element => <IngestionWizardV2 />
