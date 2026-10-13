import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { taskDefaultsLogic } from 'products/posthog_ai/frontend/logics/taskDefaultsLogic'

export function TaskDefaultsSettings(): JSX.Element {
    const { taskDefaults, myConfigLoading, taskDefaultsSaving } = useValues(taskDefaultsLogic)
    const { saveTaskDefaults, loadMyConfig } = useActions(taskDefaultsLogic)

    if (!taskDefaults) {
        return myConfigLoading ? (
            <LemonSkeleton className="h-20 max-w-200" />
        ) : (
            <LemonBanner
                type="warning"
                action={{ children: 'Try again', onClick: loadMyConfig, loading: myConfigLoading }}
                className="max-w-200"
            >
                Your task defaults did not load.
            </LemonBanner>
        )
    }

    const savingReason = taskDefaultsSaving ? 'Saving' : undefined

    return (
        <div className="flex flex-col gap-2 max-w-200">
            <LemonSwitch
                bordered
                fullWidth
                label="Start new tasks in plan mode"
                checked={taskDefaults.start_in_plan_mode ?? false}
                onChange={(start_in_plan_mode) => saveTaskDefaults({ start_in_plan_mode })}
                disabledReason={savingReason}
                data-attr="task-defaults-plan-mode"
            />
            <LemonSwitch
                bordered
                fullWidth
                label="Open a draft pull request when a cloud run changes code"
                checked={taskDefaults.auto_publish_cloud_runs ?? false}
                onChange={(auto_publish_cloud_runs) => saveTaskDefaults({ auto_publish_cloud_runs })}
                disabledReason={savingReason}
                data-attr="task-defaults-auto-publish"
            />
        </div>
    )
}
