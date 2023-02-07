import { Meta } from '@storybook/react'

import { PreflightCheck } from './PreflightCheck'

export default {
    title: 'Scenes-Other/Preflight',
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
        viewMode: 'story',
    },
} as Meta

export const Preflight = (): JSX.Element => <PreflightCheck />
