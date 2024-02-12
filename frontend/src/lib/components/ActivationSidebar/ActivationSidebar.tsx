import { LemonButton, LemonButtonWithSideActionProps } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { IconCheckmark, IconClose } from 'lib/lemon-ui/icons'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

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
