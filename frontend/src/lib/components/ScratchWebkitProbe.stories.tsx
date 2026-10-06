import { Meta, StoryObj } from '@storybook/react'

// THROWAWAY: validates the webkit pass of the flake-verification job. Reverted before merge.
const meta: Meta = {
    title: 'Scratch/Webkit Probe',
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export default meta
type Story = StoryObj

export const RendersEverywhere: Story = {
    render: () => <div>renders in every browser</div>,
}

export const BreaksInWebkitOnly: Story = {
    render: () => <div>play test throws in webkit</div>,
    play: async () => {
        if (!navigator.userAgent.includes('Chrome')) {
            throw new Error('Scratch probe: this play test fails outside chromium')
        }
    },
}
