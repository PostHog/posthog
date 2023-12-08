import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonRow } from 'lib/lemon-ui/LemonRow'

import { Lettermark, LettermarkColor } from '../Lettermark/Lettermark'
import { ProfileBubbles } from '../ProfilePicture'
import { LemonDivider, LemonDividerProps } from './LemonDivider'

type Story = StoryObj<typeof LemonDivider>
const meta: Meta<typeof LemonDivider> = {
    title: 'Lemon UI/Lemon Divider',
    component: LemonDivider,
    tags: ['autodocs'],
}
export default meta

const HorizontalTemplate: StoryFn<typeof LemonDivider> = (props: LemonDividerProps) => {
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

const VerticalTemplate: StoryFn<typeof LemonDivider> = (props: LemonDividerProps) => {
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

export const Default: Story = HorizontalTemplate.bind({})
Default.args = {}

export const OrientationLeftWithTitle: Story = HorizontalTemplate.bind({})
OrientationLeftWithTitle.args = {
    children: <span>Title</span>,
    orientation: 'left',
}

export const OrientationRightWithTitle: Story = HorizontalTemplate.bind({})
OrientationRightWithTitle.args = {
    children: <span>Title</span>,
    orientation: 'right',
}

export const OrientationCenterWithTitle: Story = HorizontalTemplate.bind({})
OrientationCenterWithTitle.args = {
    children: <span>Title</span>,
}

export const Large: Story = HorizontalTemplate.bind({})
Large.args = { className: 'my-6' }

export const ThickDashed: Story = HorizontalTemplate.bind({})
ThickDashed.args = { thick: true, dashed: true }

export const Vertical: Story = VerticalTemplate.bind({})
Vertical.args = { vertical: true }

export const VerticalDashed: Story = VerticalTemplate.bind({})
VerticalDashed.args = { vertical: true, dashed: true }
