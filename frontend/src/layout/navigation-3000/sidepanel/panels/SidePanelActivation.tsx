import { useValues } from 'kea'
import { activationLogic, ActivationTaskType } from 'lib/components/ActivationSidebar/activationLogic'
import { ActivationTask } from 'lib/components/ActivationSidebar/ActivationSidebar'
import { ProfessorHog } from 'lib/components/hedgehogs'
import { LemonIconProps } from 'lib/lemon-ui/icons'
import { LemonProgressCircle } from 'lib/lemon-ui/LemonProgressCircle'

export const SidePanelActivation = (): JSX.Element => {
    const { activeTasks, completionPercent, completedTasks } = useValues(activationLogic)

    return (
        <div className="p-4 space-y-2">
            <h2>Quick Start</h2>
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
