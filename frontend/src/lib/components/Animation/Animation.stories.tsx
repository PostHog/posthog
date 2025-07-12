import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { AnimationType } from 'lib/animations/animations'
import { Animation } from 'lib/components/Animation/Animation'

type Story = StoryObj<typeof Animation>
const meta: Meta<typeof Animation> = {
    title: 'Layout/Animations',
    parameters: {
        docs: {
            description: {
                component:
                    'Animations are [LottieFiles.com](https://lottiefiles.com/) animations that we load asynchronously.',
            },
        },
    },
    argTypes: {
        size: {
            options: ['small', 'large'],
            control: { type: 'radio' },
        },
        type: {
            options: Object.values(AnimationType),
            mapping: AnimationType,
            control: { type: 'radio' },
        },
    },
    tags: ['autodocs', 'test-skip'], // Animations aren't particularly snapshotable
}
export default meta

const Template: StoryFn<typeof Animation> = ({ size, type }): JSX.Element => {
    return <Animation type={type} size={size} />
}

export const Animations: Story = Template.bind({})
Animations.args = { size: 'large' }
