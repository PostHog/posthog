import { LemonTag } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'

import { feedbackLogic } from './inAppFeedbackLogic'

import './Feedback.scss'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { InAppFeedback } from './InAppFeedback'

export const Feedback = (): JSX.Element => {
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
                activeKey="in-app-feedback"
                onChange={function noRefCheck() {}}
                tabs={[
                    {
                        content: <InAppFeedback />,
                        key: 'in-app-feedback',
                        label: 'In-app feedback',
                    },
                    {
                        content: <div>Imagine some calculator here. 🔢</div>,
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
