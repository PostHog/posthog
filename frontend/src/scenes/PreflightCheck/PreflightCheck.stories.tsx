import { Meta } from '@storybook/react'
import type { JSX } from 'react'

import { PreflightCheck } from './PreflightCheck'

const meta: Meta = {
    title: 'Scenes-Other/Preflight',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta
export const Preflight = (): JSX.Element => <PreflightCheck />
