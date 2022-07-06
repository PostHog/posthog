import { Meta } from '@storybook/react'

import { IngestionWizard } from './IngestionWizard'

import React from 'react'

export default {
    title: 'Scenes-Other/Onboarding',
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'story' },
} as Meta

export const Ingestion = (): JSX.Element => <IngestionWizard />
