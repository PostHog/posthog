import { ComponentMeta, ComponentStory } from '@storybook/react'
import { HedgehogBuddy } from './HedgehogBuddy'

export default {
    title: 'Components/Hedgehog Buddy',
    component: HedgehogBuddy,
    parameters: {
        testOptions: { skip: true }, // Hedgehogs aren't particularly snapshotable
    },
} as ComponentMeta<typeof HedgehogBuddy>

export const TheHedgehog: ComponentStory<typeof HedgehogBuddy> = () => {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ height: 200 }}>
            <HedgehogBuddy
                onClose={() => {
                    // eslint-disable-next-line no-console
                    console.log('should close')
                }}
            />
        </div>
    )
}
