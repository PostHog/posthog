import React from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonDivider, LemonDividerProps } from './LemonDivider'
import { LemonRow } from '../LemonRow'
import { Lettermark, LettermarkColor } from '../Lettermark/Lettermark'
import { LemonButton } from '../LemonButton'
import { ProfileBubbles } from '../ProfilePicture'

export default {
    title: 'Lemon UI/Lemon Divider',
    component: LemonDivider,
} as ComponentMeta<typeof LemonDivider>

const HorizontalTemplate: ComponentStory<typeof LemonDivider> = (props: LemonDividerProps) => {
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

const VerticalTemplate: ComponentStory<typeof LemonDivider> = (props: LemonDividerProps) => {
    return (
        <div className="flex-center">
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

export const Default = HorizontalTemplate.bind({})
Default.args = {}

export const Large = HorizontalTemplate.bind({})
Large.args = { large: true }

export const Vertical = VerticalTemplate.bind({})
Vertical.args = { vertical: true }

export const ThickDashed = HorizontalTemplate.bind({})
ThickDashed.args = { thick: true, dashed: true }
