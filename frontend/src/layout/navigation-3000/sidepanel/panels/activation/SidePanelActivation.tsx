import { IconCheckCircle, IconX } from '@posthog/icons'
import { LemonButton, LemonButtonWithSideActionProps } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ProfessorHog } from 'lib/components/hedgehogs'
import { LemonIconProps } from 'lib/lemon-ui/icons'
import { LemonProgressCircle } from 'lib/lemon-ui/LemonProgressCircle'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import {
    activationLogic,
    ActivationTaskType,
} from '~/layout/navigation-3000/sidepanel/panels/activation/activationLogic'

import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'

export const SidePanelActivation = (): JSX.Element => {
    const { activeTasks, completionPercent, completedTasks } = useValues(activationLogic)

    return (
        <>
            <SidePanelPaneHeader title="Quick start" />
            <div className="p-4 space-y-2 overflow-y-auto">
                <p>Use our Quick Start guide to learn about everything PostHog can do for you and your product.</p>
                <div className="flex items-center justify-center">
                    <div className="flex flex-col items-center">
                        <LemonProgressCircle progress={completionPercent / 100} size={100} className="text-primary">
                            <span className="text-2xl">{activeTasks.length}</span>
                        </LemonProgressCircle>
                        <p className="text-muted mt-2 ">still to go</p>
                    </div>
                    <div className="h-60">
                        <ProfessorHog className="max-h-full w-auto object-contain" />
                    </div>
                </div>
                {activeTasks.length > 0 && (
                    <div>
                        <h4>What's next?</h4>
                        <ul className="space-y-2">
                            {activeTasks.map((task: ActivationTaskType) => (
                                <ActivationTask key={task.id} {...task} />
                            ))}
                        </ul>
                    </div>
                )}
                {completedTasks.length > 0 && (
                    <div>
                        <h4>Completed</h4>
                        <ul className="space-y-2">
                            {completedTasks.map((task: ActivationTaskType) => (
                                <ActivationTask key={task.id} {...task} />
                            ))}
                        </ul>
                    </div>
                )}
            </div>
        </>
    )
}

export const SidePanelActivationIcon = ({ className }: { className: LemonIconProps['className'] }): JSX.Element => {
    const { activeTasks, completionPercent } = useValues(activationLogic)

    return (
        <LemonProgressCircle progress={completionPercent / 100} strokePercentage={0.15} size={20} className={className}>
            <span className="text-xs font-semibold">{activeTasks.length}</span>
        </LemonProgressCircle>
    )
}

const ActivationTask = ({
    id,
    name,
    description,
    completed,
    canSkip,
    skipped,
    url,
}: ActivationTaskType): JSX.Element => {
    const displaySideAction = !completed && !skipped && canSkip
    const { runTask, skipTask } = useActions(activationLogic)
    const { reportActivationSideBarTaskClicked } = useActions(eventUsageLogic)

    const content = (
        <div className="my-4 mx-2">
            <p className="m-0">{name}</p>
            {!completed && !skipped && <p className="font-normal text-xs mt-2 mb-0 mx-0">{description}</p>}
        </div>
    )

    const params: Partial<LemonButtonWithSideActionProps> = {
        id,
        fullWidth: true,
        type: 'secondary',
        icon: completed ? <IconCheckCircle /> : skipped ? <IconX /> : null,
        tooltip: name,
    }
    if (url) {
        params.to = url
        params.targetBlank = true
    } else {
        params.onClick = () => {
            runTask(id)
            reportActivationSideBarTaskClicked(id)
        }
    }
    return (
        <li>
            {displaySideAction ? (
                <LemonButton
                    {...params}
                    sideAction={{
                        icon: <IconX />,
                        tooltip: 'Skip task',
                        onClick: () => skipTask(id),
                    }}
                >
                    {content}
                </LemonButton>
            ) : (
                <LemonButton {...params}>{content}</LemonButton>
            )}
        </li>
    )
}
