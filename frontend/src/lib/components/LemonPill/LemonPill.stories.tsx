import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonPill, LemonPillProps } from './LemonPill'

export default {
    title: 'Lemon UI/Lemon Pill',
    component: LemonPill,
} as ComponentMeta<typeof LemonPill>

const BasicTemplate: ComponentStory<typeof LemonPill> = (props: LemonPillProps) => {
    return <LemonPill {...props} />
}

export const Default = BasicTemplate.bind({})
Default.args = {
    children: 'Lemon Pill',
}
