import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { LemonCard as LemonCardComponent } from './LemonCard'

type Story = StoryObj<typeof LemonCardComponent>
const meta: Meta<typeof LemonCardComponent> = {
    title: 'Lemon UI/Lemon Card',
    component: LemonCardComponent,
    args: {
        children: <div>Hello</div>,
    },
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof LemonCardComponent> = (props) => {
    return <LemonCardComponent {...props} />
}

export const Default: Story = Template.bind({})
Default.args = { children: <div>Hello</div> }

export const Focused: Story = Template.bind({})
Focused.args = { children: <div>Hello</div>, focused: true }
