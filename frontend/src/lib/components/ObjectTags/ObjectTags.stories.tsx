import type { Meta, StoryObj } from '@storybook/react'

import { ObjectTags, ObjectTagsProps } from './ObjectTags'

type Story = StoryObj<typeof meta>
const meta: Meta<typeof ObjectTags> = {
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
