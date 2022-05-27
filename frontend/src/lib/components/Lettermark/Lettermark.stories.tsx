import React from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { Lettermark, LettermarkColor, LettermarkProps } from './Lettermark'

export default {
    title: 'Lemon UI/Lettermark',
    component: Lettermark,
} as ComponentMeta<typeof Lettermark>

const Template: ComponentStory<typeof Lettermark> = (props: LettermarkProps) => {
    return <Lettermark {...props} />
}

export const String = Template.bind({})
String.args = { name: 'Athena' }

export const Number = Template.bind({})
Number.args = { name: 42 }

export const Unknown = Template.bind({})
Unknown.args = { name: null }

export const Gray = Template.bind({})
Gray.args = { name: 5, color: LettermarkColor.Gray }
