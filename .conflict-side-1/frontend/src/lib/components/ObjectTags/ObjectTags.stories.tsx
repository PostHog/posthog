import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { ObjectTags, ObjectTagsProps } from './ObjectTags'

type Story = StoryObj<typeof ObjectTags>
const meta: Meta<typeof ObjectTags> = {
    title: 'Lemon UI/Object Tags',
    component: ObjectTags,
    tags: ['autodocs'],
}
export default meta

const BasicTemplate: StoryFn<typeof ObjectTags> = (props: Partial<ObjectTagsProps>) => {
    return <ObjectTags tags={['one', 'two', 'three']} {...props} />
}

export const Default: Story = BasicTemplate.bind({})
Default.args = {}

export const StaticOnly: Story = BasicTemplate.bind({})
StaticOnly.args = { staticOnly: true }
