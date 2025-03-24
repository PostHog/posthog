import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { Sparkline } from './Sparkline'

type Story = StoryObj<typeof Sparkline>
const meta: Meta<typeof Sparkline> = {
    title: 'Components/Sparkline',
    component: Sparkline,
}
export default meta

const Template: StoryFn<typeof Sparkline> = (args) => {
    return <Sparkline {...args} className="w-full" />
}

export const BarChart: Story = Template.bind({})
BarChart.args = {
    data: [10, 5, 3, 30, 22, 10, 2],
    labels: ['Mon', 'Tue', 'Wed', 'Thurs', 'Fri', 'Sat', 'Sun'],
}
