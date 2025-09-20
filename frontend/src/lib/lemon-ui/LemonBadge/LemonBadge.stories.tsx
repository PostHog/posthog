import { Meta, StoryFn, StoryObj } from '@storybook/react'
import React from 'react'

import { IconPlusSmall } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { LemonBadge, LemonBadgeProps } from './LemonBadge'

type Story = StoryObj<typeof LemonBadge>
const meta: Meta<typeof LemonBadge> = {
    title: 'Lemon UI/Lemon Badge/Lemon Badge',
    component: LemonBadge,
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof LemonBadge> = (props) => (
    <div className="flex">
        <LemonBadge {...props} />
    </div>
)

export const Standard: Story = Template.bind({})
Standard.args = { content: '@' }

export const Positioning: StoryFn<typeof LemonBadge> = () => {
    return (
        <div className="deprecated-space-y-4 m-2">
            <LemonButton type="secondary">
                top-right
                <LemonBadge content={<IconPlusSmall />} position="top-right" />
            </LemonButton>

            <LemonButton type="secondary">
                top-left
                <LemonBadge content={<IconPlusSmall />} position="top-left" />
            </LemonButton>

            <LemonButton type="secondary">
                bottom-right
                <LemonBadge content={<IconPlusSmall />} position="bottom-right" />
            </LemonButton>

            <LemonButton type="secondary">
                bottom-left
                <LemonBadge content={<IconPlusSmall />} position="bottom-left" />
            </LemonButton>
        </div>
    )
}

export const Sizes: StoryFn<typeof LemonBadge> = () => {
    return (
        <div className="flex deprecated-space-x-2 items-center">
            <span>small:</span>
            <LemonBadge content={<IconPlusSmall />} size="small" />
            <span>medium:</span>
            <LemonBadge content={<IconPlusSmall />} size="medium" />
            <span>large:</span>
            <LemonBadge content={<IconPlusSmall />} size="large" />
        </div>
    )
}

export const Status: StoryFn<typeof LemonBadge> = () => {
    const statuses = ['primary', 'success', 'warning', 'danger', 'muted', 'data']
    return (
        <div className="flex deprecated-space-x-2 items-center">
            {statuses.map((status) => (
                <React.Fragment key={status}>
                    <span>{status}</span>
                    <LemonBadge content={<IconPlusSmall />} status={status as LemonBadgeProps['status']} />
                </React.Fragment>
            ))}
        </div>
    )
}

export const Active: StoryFn<typeof LemonBadge> = () => {
    return (
        <div className="flex deprecated-space-x-2 items-center my-1 mr-1">
            <span>inactive:</span>
            <LemonBadge content={<IconPlusSmall />} />
            <span>active:</span>
            <LemonBadge content={<IconPlusSmall />} active />
        </div>
    )
}
