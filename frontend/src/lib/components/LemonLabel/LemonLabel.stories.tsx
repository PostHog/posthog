import React from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonLabel, LemonLabelProps } from './LemonLabel'

export default {
    title: 'Lemon UI/Lemon Label',
    component: LemonLabel,
    docs: {
        description: {
            component: `

[Related Figma area](https://www.figma.com/file/Y9G24U4r04nEjIDGIEGuKI/PostHog-Design-System-One?node-id=3139%3A1388)

Lemon Labels provide common styling and options for labeling form elements. They can be used directly but most commonly should be used via the \`Field\` component.

`,
        },
    },
} as ComponentMeta<typeof LemonLabel>

const Template: ComponentStory<typeof LemonLabel> = (props: LemonLabelProps) => {
    return <LemonLabel {...props} />
}

export const Basic = Template.bind({})
Basic.args = {
    info: 'This field is optional',
    children: (
        <>
            Label <span>(Optional)</span>
        </>
    ),
}

export const Overview = (): JSX.Element => {
    return (
        <div className="flex flex-col gap-2">
            <LemonLabel>Basic</LemonLabel>
            <LemonLabel info={'I am some extra info'}>Label with info</LemonLabel>

            <LemonLabel info={'I am some extra info'}>
                Label with info <span>and subinfo</span>
            </LemonLabel>
        </div>
    )
}
