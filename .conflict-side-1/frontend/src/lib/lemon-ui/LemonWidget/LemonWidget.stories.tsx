import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { LemonButton } from '../LemonButton'
import { LemonWidget, LemonWidgetProps } from './LemonWidget'

type Story = StoryObj<typeof LemonWidget>
const meta: Meta<typeof LemonWidget> = {
    title: 'Lemon UI/Lemon Widget',
    component: LemonWidget,
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof LemonWidget> = (props: LemonWidgetProps) => {
    return (
        <div>
            <LemonWidget {...props}>
                <div className="p-2">
                    <p>Some serious content here</p>
                    <p className="mb-0">and here</p>
                </div>
            </LemonWidget>
        </div>
    )
}

export const Default: Story = Template.bind({})
Default.args = {}

export const Title: Story = Template.bind({})
Title.args = { title: 'A title' }

export const Closable: Story = Template.bind({})
Closable.args = { title: 'A closable widget', onClose: () => {} }

export const Actions: Story = Template.bind({})
Actions.args = { title: 'A title', actions: <LemonButton size="small">Do this over here</LemonButton> }
