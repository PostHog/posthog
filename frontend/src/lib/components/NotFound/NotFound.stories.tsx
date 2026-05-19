import type { Meta, StoryObj } from '@storybook/react'

import { NotFound, NotFoundProps } from './index'

type Story = StoryObj<NotFoundProps>
const meta: Meta<NotFoundProps> = {
    title: 'Components/Not Found',
    component: NotFound,
}
export default meta

export const NotFound_: Story = {
    args: {
        object: 'Person',
    },
}
