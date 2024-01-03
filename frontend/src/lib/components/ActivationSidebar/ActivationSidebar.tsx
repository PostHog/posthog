import './ActivationSidebar.scss'

import { LemonButton, LemonButtonWithSideActionProps } from '@posthog/lemon-ui'
import { Progress } from 'antd'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { IconCheckmark, IconClose } from 'lib/lemon-ui/icons'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { navigationLogic } from '~/layout/navigation/navigationLogic'

import { ProfessorHog } from '../hedgehogs'
import { activationLogic, ActivationTaskType } from './activationLogic'

export const ActivationTask = ({
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
        icon: completed ? <IconCheckmark /> : skipped ? <IconClose /> : null,
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
                        icon: <IconClose />,
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

export const ActivationSidebar = (): JSX.Element => {
    const { isActivationSideBarShown } = useValues(navigationLogic)
    const { hideActivationSideBar } = useActions(navigationLogic)
    const { activeTasks, completedTasks, completionPercent } = useValues(activationLogic)

    return (
        <div className={clsx('ActivationSideBar', !isActivationSideBarShown && 'ActivationSideBar--hidden')}>
            <div className="ActivationSideBar__content pt-2 px-4 pb-16">
                <div className="ActivationSideBar__close_button">
                    <LemonButton icon={<IconClose />} onClick={() => hideActivationSideBar()} />
                </div>
                <>
                    <h2 className="subtitle">Quick Start</h2>
                    <p>Use our Quick Start guide to learn about everything PostHog can do for you and your product.</p>
                    <div className="my-4 flex items-center justify-center">
                        <div className="flex flex-col items-center">
                            <Progress
                                type="circle"
                                strokeWidth={10}
                                percent={completionPercent}
                                format={() => activeTasks.length}
                                strokeColor="#345cff" // primary-light
                            />
                            <p className="text-muted mt-2">still to go</p>
                        </div>
                        <div className="ActivationSideBar__hog">
                            <ProfessorHog className="max-h-full w-auto object-contain" />
                        </div>
                    </div>
                    {activeTasks.length > 0 && (
                        <div className="mt-4">
                            <div className="text-muted uppercase text-xs">What's next?</div>
                            <ul>
                                {activeTasks.map((task: ActivationTaskType) => (
                                    <ActivationTask key={task.id} {...task} />
                                ))}
                            </ul>
                        </div>
                    )}
                    {completedTasks.length > 0 && (
                        <div className="mt-4">
                            <div className="text-muted uppercase text-xs">Completed</div>
                            <ul>
                                {completedTasks.map((task: ActivationTaskType) => (
                                    <ActivationTask key={task.id} {...task} />
                                ))}
                            </ul>
                        </div>
                    )}
                </>
            </div>
        </div>
    )
}
