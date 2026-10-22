import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { TaskMenuItems } from 'products/posthog_ai/frontend/api/menus'

import { DROPDOWN_PARTS } from './todayMenuParts'
import { todayPanelTaskLogic } from './todayPanelTaskLogic'

interface TodayPanelTaskMenuItemsProps {
    taskId: string
    runId: string
    placement: ReactNode
}

export function TodayPanelTaskMenuItems({ taskId, runId, placement }: TodayPanelTaskMenuItemsProps): JSX.Element {
    const { task, run } = useValues(todayPanelTaskLogic({ taskId, runId }))
    const { archive } = useActions(todayPanelTaskLogic({ taskId, runId }))

    if (!task) {
        return <>{placement}</>
    }
    return <TaskMenuItems parts={DROPDOWN_PARTS} task={task} run={run} placement={placement} onArchive={archive} />
}
