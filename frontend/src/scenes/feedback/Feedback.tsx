import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { feedbackLogic } from './feedbackLogic'
import { InAppFeedback } from './InAppFeedback'

export const Feedback = (): JSX.Element => {
    return (
        <div className="Feedback">
            <PageHeader title={<div className="flex items-center gap-2">Feedback</div>} />
            <InAppFeedback />
        </div>
    )
}

export const scene: SceneExport = {
    component: Feedback,
    logic: feedbackLogic,
}
