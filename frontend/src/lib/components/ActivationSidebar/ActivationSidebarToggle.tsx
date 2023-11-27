import { LemonButton } from '@posthog/lemon-ui'
import { Progress } from 'antd'
import { useActions, useValues } from 'kea'

import { navigationLogic } from '~/layout/navigation/navigationLogic'

import { activationLogic } from './activationLogic'

export const ActivationSidebarToggle = (): JSX.Element | null => {
    const { mobileLayout } = useValues(navigationLogic)
    const { toggleActivationSideBar } = useActions(navigationLogic)
    const { activeTasks, completionPercent, isReady, hasCompletedAllTasks } = useValues(activationLogic)

    if (!isReady || hasCompletedAllTasks) {
        return null
    }
    return (
        <LemonButton
            center
            size="small"
            type="tertiary"
            onClick={toggleActivationSideBar}
            icon={
                <Progress
                    type="circle"
                    percent={completionPercent}
                    width={40}
                    format={() => activeTasks.length}
                    strokeWidth={16}
                    strokeColor="#345cff" // primary-light
                />
            }
        >
            {!mobileLayout && (
                <div className="pl-2 text-left">
                    <p className="m-0">Quick Start</p>
                    <p className="m-0 text-xs text-muted">{activeTasks.length} still to go</p>
                </div>
            )}
        </LemonButton>
    )
}
