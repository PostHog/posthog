import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { AnimatedWizardHog, type AnimatedWizardHogProps } from './AnimatedWizardHog'

const meta: Meta<typeof AnimatedWizardHog> = {
    title: 'Scenes-Other/Onboarding/Animated wizard hog',
    component: AnimatedWizardHog,
    parameters: {
        testOptions: { snapshotBrowsers: [] },
    },
    args: { speed: 1, idle: true },
    argTypes: {
        speed: { control: { type: 'range', min: 0.25, max: 4, step: 0.25 } },
    },
}

export default meta
type Story = StoryObj<typeof meta>

function CastPlayground(args: AnimatedWizardHogProps): JSX.Element {
    const [castKey, setCastKey] = useState(0)
    return (
        <div className="flex items-center gap-4">
            <AnimatedWizardHog {...args} castKey={castKey} className="w-40" />
            <LemonButton type="secondary" onClick={() => setCastKey((key) => key + 1)}>
                Cast a spell
            </LemonButton>
        </div>
    )
}

export const Playground: Story = {
    render: (args) => <CastPlayground {...args} />,
}
