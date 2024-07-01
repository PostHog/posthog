import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { Sparkline } from './Sparkline'

type Story = StoryObj<typeof Sparkline>
const meta: Meta<typeof Sparkline> = {
    title: 'Components/Sparkline',
    component: Sparkline,
}
export default meta

const Template: StoryFn<typeof Sparkline> = (props) => {
    return (
        <div className="space-y-2">
            <Sparkline {...props} />
        </div>
    )
}

export const Default: Story = Template.bind({})
Default.args = {
    data: [0, 0, 0, 1, 2, 1, 3, 45, 60, 38, 2, 10, 6, 0, 0, 0],
}

export const WithLabels: Story = Template.bind({})
WithLabels.args = {
    data: [1, 2, 1, 3],
    labels: ['Item 1', 'Item 2', 'Item 3', 'Item 4'],
}
