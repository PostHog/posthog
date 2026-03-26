import type { Meta, StoryObj } from '@storybook/react'

import { ObjectTags, ObjectTagsProps } from './ObjectTags'

type Story = StoryObj<ObjectTagsProps>
const meta: Meta<ObjectTagsProps> = {
    title: 'Lemon UI/Object Tags',
    component: ObjectTags,
    tags: ['autodocs'],
    render: (props: Partial<ObjectTagsProps>) => {
        return <ObjectTags tags={['one', 'two', 'three']} {...props} />
    },
}
export default meta

export const Default: Story = {
    args: {},
}

export const StaticOnly: Story = {
    args: { staticOnly: true },
}
