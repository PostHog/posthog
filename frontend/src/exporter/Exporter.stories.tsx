import React from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'

import { Exporter } from './Exporter'

export default {
    title: 'Layout/Exporter',
    component: Exporter,
    argTypes: {
        value: { defaultValue: 'Foo' },
    },
} as ComponentMeta<typeof Exporter>

const Template: ComponentStory<typeof Exporter> = (props) => {
    return <Exporter {...props} />
}

export const Insight = Template.bind({})
export const Dashboard = Template.bind({})
