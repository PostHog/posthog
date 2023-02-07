import { Meta } from '@storybook/react'

import { IngestionWizardV1 } from './IngestionWizard'

export default {
    title: 'Scenes-Other/Ingestion v1',
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
        viewMode: 'story',
        testOptions: { skip: true },
    },
} as Meta

export const Ingestion = (): JSX.Element => <IngestionWizardV1 />
