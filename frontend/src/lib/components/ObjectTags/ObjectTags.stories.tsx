import { ComponentMeta, ComponentStory } from '@storybook/react'
import { ObjectTags, ObjectTagsProps } from './ObjectTags'

export default {
    title: 'Lemon UI/Object Tags',
    component: ObjectTags,
} as ComponentMeta<typeof ObjectTags>

const BasicTemplate: ComponentStory<typeof ObjectTags> = (props: Partial<ObjectTagsProps>) => {
    return <ObjectTags tags={['one', 'two', 'three']} {...props} />
}

export const Default = BasicTemplate.bind({})
Default.args = {}

export const StaticOnly = BasicTemplate.bind({})
StaticOnly.args = { staticOnly: true }
