import { Meta } from '@storybook/react'

import { PreflightCheck } from './PreflightCheck'
import React from 'react'

export default {
    title: 'Scenes-Other/Onboarding',
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'canvas' },
} as Meta

export const Preflight = (): JSX.Element => <PreflightCheck />
