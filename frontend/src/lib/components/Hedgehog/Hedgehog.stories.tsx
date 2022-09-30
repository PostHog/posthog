import React from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { Hedgehog } from './Hedgehog'

export default {
    title: 'Random/Hedgehog',
    component: Hedgehog,
} as ComponentMeta<typeof Hedgehog>

export const Template: ComponentStory<typeof Hedgehog> = () => {
    return (
        <div style={{ height: 200 }}>
            <Hedgehog />
        </div>
    )
}

export const TheHedgehog = Template.bind({})
