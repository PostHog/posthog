import React from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonSnack, LemonSnackProps } from './LemonSnack'
import { ProfilePicture } from '../ProfilePicture'

export default {
    title: 'Lemon UI/Lemon Snack',
    component: LemonSnack,
    argTypes: {
        children: {
            defaultValue: 'Tasty snacks',
        },
    },
} as ComponentMeta<typeof LemonSnack>

const BasicTemplate: ComponentStory<typeof LemonSnack> = (props: LemonSnackProps) => {
    return <LemonSnack {...props} />
}

export const Default = BasicTemplate.bind({})
Default.args = {
    onClose: null as any,
}

export const ComplexContent = BasicTemplate.bind({})
ComplexContent.args = {
    children: (
        <span className="flex gap-2 items-center">
            <ProfilePicture email="ben@posthog.com" size="sm" />
            <span>
                Look at me I'm <b>bold!</b>
            </span>
        </span>
    ),
    onClose: () => alert('Close clicked!'),
}
