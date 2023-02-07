import { Meta } from '@storybook/react'

import { Unsubscribe } from './Unsubscribe'

export default {
    title: 'Scenes-Other/Unsubscribe',
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
        viewMode: 'story',
    },
} as Meta

export const UnsubscribeScene = (): JSX.Element => <Unsubscribe />
