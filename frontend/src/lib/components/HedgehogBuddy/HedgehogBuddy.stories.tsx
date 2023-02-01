import { ComponentMeta, ComponentStory } from '@storybook/react'
import { HedgehogBuddy } from './HedgehogBuddy'

export default {
    title: 'Components/Hedgehog Buddy',
    component: HedgehogBuddy,
    parameters: {
        chromatic: { disableSnapshot: true },
    },
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
