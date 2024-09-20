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
        <div className="h-52">
            <MyHedgehogBuddy
                onClose={() => {
                    // eslint-disable-next-line no-console
                    console.log('should close')
                }}
            />
        </div>
    )
}
