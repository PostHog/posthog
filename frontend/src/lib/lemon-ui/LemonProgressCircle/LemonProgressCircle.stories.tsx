import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useEffect, useState } from 'react'

import { IconGear } from '@posthog/icons'

import { LemonButton } from '../LemonButton'
import { LemonCheckbox } from '../LemonCheckbox'
import { LemonProgressCircle, LemonProgressCircleProps } from './LemonProgressCircle'

type Story = StoryObj<typeof LemonProgressCircle>
const meta: Meta<typeof LemonProgressCircle> = {
    title: 'Lemon UI/Lemon Progress Circle',
    component: LemonProgressCircle,
    parameters: {
        docs: {
            description: {
                component: `

[Related Figma area](https://www.figma.com/file/Y9G24U4r04nEjIDGIEGuKI/PostHog-Design-System-One?node-id=3139%3A1388)

Lemon Labels provide common styling and options for labeling form elements. They can be used directly but most commonly should be used via the \`Field\` component.

`,
            },
        },
    },
    args: {
        progress: 0.3,
    },
    tags: ['autodocs'],
}
export default meta

export const Template: StoryFn<typeof LemonProgressCircle> = (props: LemonProgressCircleProps) => {
    return <LemonProgressCircle {...props} />
}

export const Basic: Story = Template.bind({})
Basic.args = {
    progress: 0.3,
}

export const Overview = (): JSX.Element => {
    const [progress, setProgress] = useState(0.2)
    const [animate, setAnimate] = useState(false)

    useEffect(() => {
        if (!animate) {
            return
        }
        const interval = setInterval(() => {
            setProgress((progress) => {
                const newProgress = progress + 0.1
                return newProgress > 1 ? newProgress - 1 : newProgress
            })
        }, 500)
        return () => clearInterval(interval)
    }, [animate])

    return (
        <div className="flex flex-col gap-2">
            <LemonCheckbox checked={animate} onChange={setAnimate} bordered label="Animate" />
            <LemonProgressCircle progress={progress} />
            <LemonProgressCircle progress={progress} strokePercentage={0.5} size={30} />

            <span className="flex items-center gap-2">
                <LemonButton
                    icon={<LemonProgressCircle progress={progress} />}
                    sideIcon={<IconGear />}
                    type="secondary"
                    size="small"
                >
                    In a button!
                </LemonButton>

                <LemonButton
                    icon={<LemonProgressCircle progress={progress} size={20} />}
                    sideIcon={<IconGear />}
                    type="secondary"
                >
                    In a button!
                </LemonButton>

                <LemonButton
                    icon={<LemonProgressCircle progress={progress} size={24} />}
                    sideIcon={<IconGear />}
                    type="secondary"
                    size="large"
                >
                    In a button!
                </LemonButton>
            </span>

            <LemonProgressCircle progress={progress} size={40}>
                <span className="font-semibold text-sm">{(100 * progress).toFixed(0)}</span>
            </LemonProgressCircle>

            <span>
                Here is one inline <LemonProgressCircle progress={progress} /> with some text...
            </span>
        </div>
    )
}
