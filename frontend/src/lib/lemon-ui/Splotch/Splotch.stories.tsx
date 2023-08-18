import { StoryObj, Meta } from '@storybook/react'
import { Splotch, SplotchColor, SplotchProps } from './Splotch'

const meta: Meta<typeof Splotch> = {
    title: 'Lemon UI/Splotch',
    component: Splotch,
    args: {
        color: SplotchColor.Purple,
    },
    tags: ['autodocs'],
}
export default meta

export const _Splotch: StoryObj<typeof Splotch> = {
    render: (props: SplotchProps) => {
        return <Splotch {...props} />
    },
}
