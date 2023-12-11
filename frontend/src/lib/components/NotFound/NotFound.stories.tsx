import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { NotFound } from './index'

type Story = StoryObj<typeof NotFound>
const meta: Meta<typeof NotFound> = {
    title: 'Components/Not Found',
    component: NotFound,
}
export default meta

const Template: StoryFn<typeof NotFound> = (args) => <NotFound {...args} />

export const NotFound_: Story = Template.bind({})
NotFound_.args = {
    object: 'Person',
}
