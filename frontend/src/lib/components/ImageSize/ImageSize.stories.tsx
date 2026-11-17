import { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import { useState } from 'react'

import { userEvent } from 'storybook/test'

import { ImageSize } from './ImageSize'

const meta: Meta<typeof ImageSize> = {
    title: 'Components/Image size',
    component: ImageSize,
    args: {
        description: 'Leave a dimension blank to size it automatically. Content fits without stretching or cropping.',
        value: { width: 1200, height: 630 },
    },
    render: (args) => {
        const [value, setValue] = useState(args.value)
        return (
            <div className="max-w-100">
                <ImageSize {...args} value={value} onChange={setValue} />
            </div>
        )
    },
}
export default meta
type Story = StoryObj<typeof ImageSize>
export const Custom: Story = {
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByText('Size: 1200 × 630 px'))
    },
}
