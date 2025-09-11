import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { Textfit } from './Textfit'

type Story = StoryObj<typeof Textfit>
const meta: Meta<typeof Textfit> = {
    title: 'Lemon UI/TextFit',
    component: Textfit,
    tags: ['autodocs'],
    args: {
        min: 20,
        max: 150,
        children: '10000000',
    },
}
export default meta

const Template: StoryFn<typeof Textfit> = (props) => {
    return (
        <div className="resize w-100 h-50 overflow-hidden border rounded">
            <Textfit {...props} />
        </div>
    )
}

export const Basic: Story = Template.bind({})
