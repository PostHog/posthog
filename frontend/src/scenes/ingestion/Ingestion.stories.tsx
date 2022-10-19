import { Meta } from '@storybook/react'

import { IngestionWizard } from './IngestionWizard'

export default {
    title: 'Scenes-Other/Onboarding',
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'story' },
} as Meta

export const Ingestion = (): JSX.Element => <IngestionWizard />
