import { IconNotebook } from '@posthog/icons'
import { ChatTask } from '@posthog/quill'

import { Activity } from 'products/posthog_ai/frontend/api/primitives'

import type { PlanningAnswerProps } from '../PlanningAnswer'
import { PLAN_STEP_STATUS, parsePlanningSteps } from '../planningSteps'

/** The plan as the shared activity row, so it opens and closes like the tool calls around it. */
export function QuillPlanningAnswer({ toolCall, isLastPlanningMessage = true }: PlanningAnswerProps): JSX.Element {
    const steps = parsePlanningSteps(toolCall)
    const completedCount = steps.filter((step) => step.status === 'completed').length

    return (
        <Activity
            id={toolCall.id}
            title="Planning"
            subtitle={`${completedCount}/${steps.length}`}
            status="completed"
            defaultOpen={isLastPlanningMessage}
            icon={<IconNotebook />}
            details={
                steps.length > 1 ? (
                    <ol className="quill-chat-task-list__items p-0">
                        {steps.map((step, index) => (
                            <ChatTask key={index} status={PLAN_STEP_STATUS[step.status] ?? 'pending'}>
                                {step.description}
                            </ChatTask>
                        ))}
                    </ol>
                ) : null
            }
        />
    )
}
