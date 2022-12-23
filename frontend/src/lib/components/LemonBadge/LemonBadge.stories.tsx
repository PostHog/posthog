import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonBadge } from './LemonBadge'
import { LemonButton } from '../LemonButton'
import { IconPlusMini } from '../icons'

export default {
    title: 'Lemon UI/Lemon Badge/Lemon Badge',
    component: LemonBadge,
    parameters: {
        chromatic: { disableSnapshot: false },
    },
} as ComponentMeta<typeof LemonBadge>

const Template: ComponentStory<typeof LemonBadge> = (props) => (
    <div className="flex">
        <LemonBadge {...props} />
    </div>
)

export const Standard = Template.bind({})
Standard.args = { content: '@' }

export const Positioning: ComponentStory<typeof LemonBadge> = () => {
    return (
        <div className="space-y-4 m-2">
            <LemonButton type="secondary">
                top-right
                <LemonBadge content={<IconPlusMini />} position="top-right" />
            </LemonButton>

            <LemonButton type="secondary">
                top-left
                <LemonBadge content={<IconPlusMini />} position="top-left" />
            </LemonButton>

            <LemonButton type="secondary">
                bottom-right
                <LemonBadge content={<IconPlusMini />} position="bottom-right" />
            </LemonButton>

            <LemonButton type="secondary">
                bottom-left
                <LemonBadge content={<IconPlusMini />} position="bottom-left" />
            </LemonButton>
        </div>
    )
}

export const Sizes: ComponentStory<typeof LemonBadge> = () => {
    return (
        <div className="flex space-x-2 items-center">
            <span>small:</span>
            <LemonBadge content={<IconPlusMini />} size="small" />
            <span>medium:</span>
            <LemonBadge content={<IconPlusMini />} size="medium" />
            <span>large:</span>
            <LemonBadge content={<IconPlusMini />} size="large" />
        </div>
    )
}

export const Status: ComponentStory<typeof LemonBadge> = () => {
    return (
        <div className="flex space-x-2 items-center">
            <span>primary:</span>
            <LemonBadge content={<IconPlusMini />} status="primary" />
            <span>danger:</span>
            <LemonBadge content={<IconPlusMini />} status="danger" />
            <span>muted:</span>
            <LemonBadge content={<IconPlusMini />} status="muted" />
        </div>
    )
}

export const Active: ComponentStory<typeof LemonBadge> = () => {
    return (
        <div className="flex space-x-2 items-center my-1 mr-1">
            <span>inactive:</span>
            <LemonBadge content={<IconPlusMini />} />
            <span>active:</span>
            <LemonBadge content={<IconPlusMini />} active />
        </div>
    )
}
