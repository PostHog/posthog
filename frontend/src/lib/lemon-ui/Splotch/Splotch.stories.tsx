import { Meta, StoryObj } from '@storybook/react'

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

type Story = StoryObj<SplotchProps>

export const _Splotch: Story = {
    render: (props) => {
        return <Splotch {...props} />
    },
}
