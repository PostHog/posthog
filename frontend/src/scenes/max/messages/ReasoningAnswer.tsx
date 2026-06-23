import { IconBrain } from '@posthog/icons'

import { inStorybookTestRunner } from 'lib/utils/dom'

import { TaskExecutionStatus as ExecutionStatus } from '~/queries/schema/schema-assistant-messages'

import { LangGraphActivity } from '../components/Activity'

export interface ReasoningAnswerProps {
    content: string
    completed: boolean
    id: string
    showCompletionIcon?: boolean
    animate?: boolean
}

export function ReasoningAnswer({
    content,
    completed,
    id,
    showCompletionIcon = true,
    animate = false,
}: ReasoningAnswerProps): JSX.Element {
    return (
        <LangGraphActivity
            id={id}
            content={completed ? 'Thought' : content}
            substeps={completed ? [content] : []}
            state={completed ? ExecutionStatus.Completed : ExecutionStatus.InProgress}
            icon={<IconBrain />}
            animate={!inStorybookTestRunner() && animate} // Avoiding flaky snapshots in Storybook
            showCompletionIcon={showCompletionIcon}
        />
    )
}
