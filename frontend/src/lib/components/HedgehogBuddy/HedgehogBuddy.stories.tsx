import { Meta, StoryFn } from '@storybook/react'

import { MyHedgehogBuddy } from './HedgehogBuddy'

const meta: Meta<typeof MyHedgehogBuddy> = {
    title: 'Components/Hedgehog Buddy',
    component: MyHedgehogBuddy,
    tags: ['test-skip'], // Hedgehogs aren't particularly snapshotable
}
export default meta

export const TheHedgehog: StoryFn<typeof MyHedgehogBuddy> = () => {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ height: 200 }}>
            <MyHedgehogBuddy
                onClose={() => {
                    // eslint-disable-next-line no-console
                    console.log('should close')
                }}
            />
        </div>
    )
}
