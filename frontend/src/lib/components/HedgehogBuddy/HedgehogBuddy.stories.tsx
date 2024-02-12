import { Meta, StoryFn } from '@storybook/react'

import { HedgehogBuddy } from './HedgehogBuddy'

const meta: Meta<typeof HedgehogBuddy> = {
    title: 'Components/Hedgehog Buddy',
    component: HedgehogBuddy,
    tags: ['test-skip'], // Hedgehogs aren't particularly snapshotable
}
export default meta

export const TheHedgehog: StoryFn<typeof HedgehogBuddy> = () => {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ height: 200 }}>
            <HedgehogBuddy
                onClose={() => {
                    // eslint-disable-next-line no-console
                    console.log('should close')
                }}
                isDarkModeOn={false}
            />
        </div>
    )
}
