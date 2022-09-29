import React from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { Splotch, SplotchColor, SplotchProps } from './Splotch'

export default {
    title: 'Lemon UI/Splotch',
    component: Splotch,
    argTypes: {
        color: {
            defaultValue: SplotchColor.Purple,
        },
    },
} as ComponentMeta<typeof Splotch>

export const _Splotch: ComponentStory<typeof Splotch> = (props: SplotchProps) => {
    return <Splotch {...props} />
}
