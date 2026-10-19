import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { TaskMenuItems } from 'products/posthog_ai/frontend/api/primitives'

import { DROPDOWN_PARTS } from './todayMenuParts'
import { todayPanelTaskLogic } from './todayPanelTaskLogic'

interface TodayPanelTaskMenuItemsProps {
    taskId: string
    placement: ReactNode
}

export function TodayPanelTaskMenuItems({ taskId, placement }: TodayPanelTaskMenuItemsProps): JSX.Element {
    const { task } = useValues(todayPanelTaskLogic({ taskId }))
    const { archive } = useActions(todayPanelTaskLogic({ taskId }))

    if (!task) {
        return <>{placement}</>
    }
    return (
        <TaskMenuItems
            parts={DROPDOWN_PARTS}
            task={task}
            run={task.latest_run}
            placement={placement}
            onArchive={archive}
        />
    )
}
