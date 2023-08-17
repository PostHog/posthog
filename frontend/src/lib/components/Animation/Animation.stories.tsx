import { AnimationType } from 'lib/animations/animations'
import { StoryFn, Meta, StoryObj } from '@storybook/react'
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
        testOptions: { skip: true }, // Animations aren't particularly snapshotable
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
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof Animation> = ({ size, type }): JSX.Element => {
    return <Animation type={type} size={size} />
}

export const Animations: Story = Template.bind({})
Animations.args = { size: 'large' }
