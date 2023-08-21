import { Meta } from '@storybook/react'

import { Unsubscribe } from './Unsubscribe'

const meta: Meta = {
    title: 'Scenes-Other/Unsubscribe',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta
export const UnsubscribeScene = (): JSX.Element => <Unsubscribe />
