import { Meta, StoryFn } from '@storybook/react'

import { Splotch, SplotchColor, SplotchProps } from './Splotch'

const meta: Meta<SplotchProps> = {
    title: 'Lemon UI/Splotch',
    component: Splotch,
    args: {
        color: SplotchColor.Purple,
    },
    tags: ['autodocs'],
}
export default meta

export const _Splotch: StoryFn<SplotchProps> = (props) => {
    return <Splotch {...props} />
}
