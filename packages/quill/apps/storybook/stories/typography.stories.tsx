import type { Meta, StoryObj } from '@storybook/react'

const meta = {
    title: 'Tokens/Typography',
    tags: ['autodocs'],
} satisfies Meta

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => {
        return (
            <div className="space-y-6">
                <h1 className="text-2xl font-bold">Text-2xl - largest</h1>
                <h2 className="text-xl font-bold">Text-xl - large</h2>
                <h3 className="text-lg font-bold">Text-lg - medium</h3>
                <h4 className="text-base font-bold">Text-base - normal</h4>
                <h5 className="text-sm font-bold">Text-sm - smaller</h5>
                <p className="text-xs">Text-xs - small</p>
                <small className="text-xxs">Text-xxs - super small</small>
            </div>
        )
    },
}
