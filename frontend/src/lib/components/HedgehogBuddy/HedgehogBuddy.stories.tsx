import React from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { HedgehogBuddy } from './HedgehogBuddy'

export default {
    title: 'Random/HedgehogBuddy',
    component: HedgehogBuddy,
} as ComponentMeta<typeof HedgehogBuddy>

export const Template: ComponentStory<typeof HedgehogBuddy> = () => {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ height: 200 }}>
            <HedgehogBuddy onClose={() => console.log('should close')} />
        </div>
    )
}

export const TheHedgehog = Template.bind({})
