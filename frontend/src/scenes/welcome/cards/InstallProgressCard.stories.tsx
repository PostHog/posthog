import { MOCK_TEAM_ID } from 'lib/api.mock'

import { Meta, StoryFn } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { useEffect } from 'react'

import { activeCloudRunLogic } from 'scenes/onboarding/shared/wizard-sync/activeCloudRunLogic'

import { mswDecorator } from '~/mocks/browser'

import { InstallProgressCard } from './InstallProgressCard'

const meta: Meta<typeof InstallProgressCard> = {
    title: 'Scenes-Other/Welcome/InstallProgressCard',
    component: InstallProgressCard,
    parameters: {
        layout: 'padded',
        testOptions: { include: false },
    },
    decorators: [mswDecorator({})],
}
export default meta

// The card only renders while there's an active cloud run for the current project, so seed one
// (the storybook app context sets current_project to MOCK_TEAM_ID).
export const Default: StoryFn<typeof InstallProgressCard> = () => {
    useMountedLogic(activeCloudRunLogic)
    useEffect(() => {
        activeCloudRunLogic.actions.setActiveCloudRun('task-1', 'run-1', new Date().toISOString(), MOCK_TEAM_ID)
    }, [])
    return (
        <div className="max-w-[608px]">
            <InstallProgressCard />
        </div>
    )
}
