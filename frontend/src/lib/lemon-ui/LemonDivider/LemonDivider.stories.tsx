import type { Meta, StoryObj } from '@storybook/react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonRow } from 'lib/lemon-ui/LemonRow'

import { Lettermark, LettermarkColor } from '../Lettermark/Lettermark'
import { ProfileBubbles } from '../ProfilePicture'
import { LemonDivider, LemonDividerProps } from './LemonDivider'

type Story = StoryObj<LemonDividerProps>
const meta: Meta<LemonDividerProps> = {
    title: 'Lemon UI/Lemon Divider',
    component: LemonDivider,
    tags: ['autodocs'],
}
export default meta

const HorizontalRender = (props: LemonDividerProps): JSX.Element => {
    return (
        <>
            <LemonRow icon={<Lettermark name={1} color={LettermarkColor.Gray} />}>
                I just wanna tell you how I'm feeling
            </LemonRow>
            <LemonRow icon={<Lettermark name={2} color={LettermarkColor.Gray} />}>Gotta make you understand</LemonRow>
            <LemonDivider {...props} />
            <LemonRow icon={<Lettermark name={3} color={LettermarkColor.Gray} />}>Never gonna give you up</LemonRow>
            <LemonRow icon={<Lettermark name={4} color={LettermarkColor.Gray} />}>Never gonna let you down</LemonRow>
        </>
    )
}

const VerticalRender = (props: LemonDividerProps): JSX.Element => {
    return (
        <div className="flex items-center">
            <ProfileBubbles
                people={[
                    {
                        email: 'tim@posthog.com',
                    },
                    {
                        email: 'michael@posthog.com',
                    },
                ]}
            />
            <LemonDivider {...props} />
            <LemonButton type="secondary">Collaborate</LemonButton>
        </div>
    )
}

export const Default: Story = {
    args: {},
    render: (props) => <HorizontalRender {...props} />,
}

export const Large: Story = {
    args: { className: 'my-6' },
    render: (props) => <HorizontalRender {...props} />,
}

export const ThickDashed: Story = {
    args: { thick: true, dashed: true },
    render: (props) => <HorizontalRender {...props} />,
}

export const Vertical: Story = {
    args: { vertical: true },
    render: (props) => <VerticalRender {...props} />,
}

export const VerticalDashed: Story = {
    args: { vertical: true, dashed: true },
    render: (props) => <VerticalRender {...props} />,
}
