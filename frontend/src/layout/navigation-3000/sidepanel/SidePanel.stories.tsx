import { Meta, StoryFn } from '@storybook/react'
import { App } from 'scenes/App'

const meta: Meta = {
    title: 'Scenes-App/SidePanels',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-07-04', // To stabilize relative dates
    },
}
export default meta
export const SidePanelDocs: StoryFn = () => {
    return <App />
}
