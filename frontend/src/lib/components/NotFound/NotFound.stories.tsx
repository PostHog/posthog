import type { Meta, StoryObj } from '@storybook/react'

import { NotFound } from './index'

type Story = StoryObj<typeof meta>
const meta: Meta<typeof NotFound> = {
    title: 'Components/Not Found',
    component: NotFound,
}
export default meta

export const NotFound_: Story = {
    args: {
        object: 'Person',
    },
}
