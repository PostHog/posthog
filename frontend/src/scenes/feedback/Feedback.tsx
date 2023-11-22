import { LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'

import { feedbackLogic } from './feedbackLogic'
import { InAppFeedback, InAppFeedbackHeaderButtons } from './InAppFeedback'
import { UserInterviewScheduler, UserInterviewSchedulerHeaderButtons } from './UserInterviewScheduler'

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
                buttons={
                    activeTab === 'in-app-feedback' ? (
                        <InAppFeedbackHeaderButtons />
                    ) : (
                        <UserInterviewSchedulerHeaderButtons />
                    )
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
                    },
                    {
                        content: <UserInterviewScheduler />,
                        key: 'user-interview-scheduler',
                        label: 'User interview scheduler',
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
