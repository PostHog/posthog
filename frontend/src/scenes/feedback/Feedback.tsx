import { LemonTag } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'

import { feedbackLogic } from './feedbackLogic'

import './Feedback.scss'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { InAppFeedback } from './InAppFeedback'
import { UserInterviewScheduler } from './UserInterviewScheduler'
import { useActions, useValues } from 'kea'

export const Feedback = (): JSX.Element => {
    const { activeTab } = useValues(feedbackLogic)
    const { setActiveTab } = useActions(feedbackLogic)
    return (
        <div className="Feedback">
            <PageHeader
                title={
                    <div className="flex items-center gap-2">
                        Feedback
                        <LemonTag type="warning" className="uppercase">
                            Alpha
                        </LemonTag>
                    </div>
                }
            />
            <LemonTabs
                activeKey={activeTab}
                onChange={(key) => {
                    setActiveTab(key)
                }}
                tabs={[
                    {
                        content: <InAppFeedback />,
                        key: 'in-app-feedback',
                        label: 'In-app feedback',
                        tooltip: 'Analyze feedback from your users',
                    },
                    {
                        content: <UserInterviewScheduler />,
                        key: 'user-interview-scheduler',
                        label: 'User interview scheduler',
                        tooltip: 'Schedule user interviews with your users',
                    },
                ]}
            />
        </div>
    )
}

export const scene: SceneExport = {
    component: Feedback,
    logic: feedbackLogic,
}
