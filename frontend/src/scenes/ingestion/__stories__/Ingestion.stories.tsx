import { Meta } from '@storybook/react'

import { IngestionWizard } from '../IngestionWizard'

import React from 'react'

export default {
    title: 'Scenes/Onboarding',
    parameters: { layout: 'fullscreen', options: { showPanel: false /* hide code for scenes */ } },
} as Meta

export const Ingestion = (): JSX.Element => <IngestionWizard />
