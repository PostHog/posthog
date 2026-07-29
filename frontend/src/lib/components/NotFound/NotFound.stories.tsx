import type { Meta, StoryObj } from '@storybook/react'

import { NotFound, NotFoundProps } from './index'

type Story = StoryObj<NotFoundProps>
const meta: Meta<NotFoundProps> = {
    title: 'Components/Not Found',
    component: NotFound,
}
export default meta

// Lowercase `person`, matching what every caller passes — and a urlId, without which the
// caption points at an event search whose button never renders.
export const NotFound_: Story = {
    args: {
        object: 'person',
        meta: { urlId: '019f9c1f-7a3c-7c2f-9e15-2c7f4b1d8e60' },
    },
}

export const NotFoundGenericObject: Story = {
    args: {
        object: 'dashboard',
    },
}
