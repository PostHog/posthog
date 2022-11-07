import { Meta } from '@storybook/react'

import { IngestionWizardV1 } from './IngestionWizard'

export default {
    title: 'Scenes-Other/Onboarding',
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'story' },
} as Meta

export const IngestionV1 = (): JSX.Element => <IngestionWizardV1 />
