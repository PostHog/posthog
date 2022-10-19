import { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonLabel, LemonLabelProps } from './LemonLabel'
import { LemonModal } from '@posthog/lemon-ui'

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
    showOptional: true,
    children: 'Label',
}

function ExplanationModal({ setOpen, open }: { setOpen: (open: boolean) => void; open: boolean }): JSX.Element {
    return (
        <LemonModal title="Let me explain you the label" isOpen={open} onClose={() => setOpen(false)}>
            <div className="bg-white w-full max-w-lg h-full ml-auto relative z-10 overflow-auto">
                <h3 className="text-lg text-semibold opacity-50 m-0">Labels are awesome.</h3>
                <p>They truly are.</p>
            </div>
        </LemonModal>
    )
}

export const Overview = (): JSX.Element => {
    const [open, setOpen] = useState(false)
    return (
        <div className="flex flex-col gap-2">
            <LemonLabel>Basic</LemonLabel>
            <LemonLabel info={'I am some extra info'}>Label with info</LemonLabel>

            <LemonLabel info={'I am some extra info'} showOptional>
                Pineapple on Pizza
            </LemonLabel>
            <LemonLabel info={'I am some extra info'}>
                Label with info <span>custom subtext</span>
            </LemonLabel>
            <LemonLabel onExplanationClick={() => setOpen(true)}>Label with explanation modal</LemonLabel>
            <ExplanationModal open={open} setOpen={setOpen} />
        </div>
    )
}
