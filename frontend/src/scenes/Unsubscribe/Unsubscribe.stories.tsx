import { Meta } from '@storybook/react'

import { Unsubscribe } from './Unsubscribe'
import React from 'react'

export default {
    title: 'Scenes-Other/Unsubscribe',
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'canvas' },
} as Meta

export const UnsubscribeScene = (): JSX.Element => <Unsubscribe />
