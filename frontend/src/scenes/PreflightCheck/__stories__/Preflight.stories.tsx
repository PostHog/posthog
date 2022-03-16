import { Meta } from '@storybook/react'

import { PreflightCheck } from '../index'
import React from 'react'

export default {
    title: 'Scenes/Onboarding',
} as Meta

export const Preflight = (): JSX.Element => <PreflightCheck />
