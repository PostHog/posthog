import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { useActions, useMountedLogic } from 'kea'
import { useEffect } from 'react'

import { userLogic } from 'scenes/userLogic'

import { InAppOnboarding } from './InAppOnboarding'
import { COMMAND_K_FLOW } from './inAppOnboardingFlows'
import { inAppOnboardingLogic } from './inAppOnboardingLogic'
import { InAppOnboardingProgress } from './inAppOnboardingProgress'

const meta: Meta = {
    title: 'Components/In-app onboarding',
    parameters: {
        layout: 'fullscreen',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj<{}>

function Frame({ progress }: { progress: InAppOnboardingProgress }): JSX.Element {
    useMountedLogic(inAppOnboardingLogic)
    const { loadUserSuccess } = useActions(userLogic)
    const { setProgress, completeFlow } = useActions(inAppOnboardingLogic)
    useEffect(() => {
        loadUserSuccess({ ...MOCK_DEFAULT_USER, has_seen_product_intro_for: {} })
        setProgress(COMMAND_K_FLOW.key, progress)
        if (progress.stepIndex >= COMMAND_K_FLOW.steps.length) {
            completeFlow(COMMAND_K_FLOW.key)
        }
    }, [progress, loadUserSuccess, setProgress, completeFlow])
    return (
        <div className="h-[320px] bg-primary">
            <InAppOnboarding />
        </div>
    )
}

export const FirstStep: Story = {
    render: () => <Frame progress={{ stepIndex: 0, count: 0 }} />,
}

export const PracticeHalfway: Story = {
    render: () => <Frame progress={{ stepIndex: 2, count: 2 }} />,
}

export const Finished: Story = {
    render: () => <Frame progress={{ stepIndex: COMMAND_K_FLOW.steps.length, count: 0 }} />,
}
