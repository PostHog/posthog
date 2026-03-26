import type { Meta, StoryObj } from '@storybook/react'

import { IconInfo } from '@posthog/icons'

import { LemonCollapse as LemonCollapseComponent, type LemonCollapseProps } from './LemonCollapse'

type Story = StoryObj<LemonCollapseProps<string>>
const meta: Meta<LemonCollapseProps<string>> = {
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

export const Single: Story = {
    args: { defaultActiveKey: '1' },
}

export const Multiple: Story = {
    args: { defaultActiveKeys: ['1', '2'], multiple: true },
}

export const Small: Story = {
    args: { size: 'small', multiple: true },
}

export const Large: Story = {
    args: { size: 'large', multiple: true },
}

export const CustomizedHeaders: Story = {
    args: {
        panels: [
            {
                key: '1',
                header: {
                    sideAction: {
                        onClick: () => alert('You clicked me!'),
                        icon: <IconInfo />,
                    },
                    children: (
                        <span className="text-sm">
                            I am <span className="italic">customized...</span>
                        </span>
                    ),
                },
                content: <span>Panel 1 content</span>,
            },
            {
                key: '2',
                header: 'I am not :(',
                content: <span>Panel 2 content</span>,
            },
        ],
    },
}
