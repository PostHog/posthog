import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { agentPreferencesLogic } from 'products/posthog_ai/frontend/logics/agentPreferencesLogic'

export function TaskDefaultsSettings(): JSX.Element {
    const { agentPreferences, agentPreferencesLoading } = useValues(agentPreferencesLogic)
    const { saveAgentPreferences, loadAgentPreferences } = useActions(agentPreferencesLogic)

    if (!agentPreferences) {
        return agentPreferencesLoading ? (
            <LemonSkeleton className="h-20 max-w-200" />
        ) : (
            <LemonBanner
                type="warning"
                action={{ children: 'Try again', onClick: loadAgentPreferences, loading: agentPreferencesLoading }}
                className="max-w-200"
            >
                Your task defaults did not load.
            </LemonBanner>
        )
    }

    const savingReason = agentPreferencesLoading ? 'Saving' : undefined

    return (
        <div className="flex flex-col gap-2 max-w-200">
            <LemonSwitch
                bordered
                fullWidth
                label="Start new tasks in plan mode"
                checked={agentPreferences.start_in_plan_mode}
                onChange={(start_in_plan_mode) => saveAgentPreferences({ start_in_plan_mode })}
                disabledReason={savingReason}
                data-attr="task-defaults-plan-mode"
            />
            <LemonSwitch
                bordered
                fullWidth
                label="Open a draft pull request when a cloud run changes code"
                checked={agentPreferences.auto_publish_cloud_runs}
                onChange={(auto_publish_cloud_runs) => saveAgentPreferences({ auto_publish_cloud_runs })}
                disabledReason={savingReason}
                data-attr="task-defaults-auto-publish"
            />
        </div>
    )
}
