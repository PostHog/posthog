import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { LemonCollapse as LemonCollapseComponent } from './LemonCollapse'

type Story = StoryObj<typeof LemonCollapseComponent>
const meta: Meta<typeof LemonCollapseComponent> = {
    title: 'Lemon UI/Lemon Collapse',
    component: LemonCollapseComponent,
    args: {
        panels: [
            {
                key: '1',
                header: 'Panel 1',
                content: <span>Panel 1 content</span>,
            },
            {
                key: '2',
                header: 'Panel 2',
                content: <span>Panel 2 content</span>,
            },
        ],
    },
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof LemonCollapseComponent> = (props) => {
    return <LemonCollapseComponent {...props} />
}

export const Single: Story = {
    render: Template,
    args: { defaultActiveKey: '1' },
}

export const Multiple: Story = {
    render: Template,
    args: { defaultActiveKeys: ['1', '2'], multiple: true },
}
