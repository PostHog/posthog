import type { Meta, StoryObj } from '@storybook/react'

import { LemonButton } from '../LemonButton'
import { LemonWidget, LemonWidgetProps } from './LemonWidget'

type Story = StoryObj<LemonWidgetProps>
const meta: Meta<LemonWidgetProps> = {
    title: 'Lemon UI/Lemon Widget',
    component: LemonWidget,
    tags: ['autodocs'],
    render: (props) => {
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
    },
}
export default meta

export const Default: Story = {
    args: {},
}

export const Title: Story = {
    args: { title: 'A title' },
}

export const Closable: Story = {
    args: { title: 'A closable widget', onClose: () => {} },
}

export const Actions: Story = {
    args: { title: 'A title', actions: <LemonButton size="small">Do this over here</LemonButton> },
}
