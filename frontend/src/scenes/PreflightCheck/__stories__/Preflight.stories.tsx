import { Meta } from '@storybook/react'

import { PreflightCheck } from '../index'
import React from 'react'

export default {
    title: 'Scenes/Onboarding',
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'canvas' },
} as Meta

export const Preflight = (): JSX.Element => <PreflightCheck />
