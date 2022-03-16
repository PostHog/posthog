import { Meta } from '@storybook/react'

import { IngestionWizard } from '../IngestionWizard'

import React from 'react'

export default {
    title: 'Scenes/Onboarding',
} as Meta

export const Ingestion = (): JSX.Element => <IngestionWizard />
