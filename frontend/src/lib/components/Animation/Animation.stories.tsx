import * as React from 'react'
import { AnimationType } from 'lib/animations/animations'
import { ComponentStory, Meta } from '@storybook/react'
import { Animation } from 'lib/components/Animation/Animation'

console.log(Object.keys(AnimationType))

export default {
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
} as Meta<Animation>

const Template: ComponentStory<typeof Animation> = ({ size, type }): JSX.Element => {
    return <Animation type={type} size={size} />
}

export const Animations = Template.bind({})
Animations.args = { size: 'large' }
