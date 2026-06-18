import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { DEFAULT_LOGS_DISTINCT_ID_ATTRIBUTE_KEY, logsConfigLogic } from 'products/logs/frontend/logsConfigLogic'

export function LogsDistinctIdAttributeKey(): JSX.Element {
    const { logsConfig, logsConfigLoading } = useValues(logsConfigLogic)
    const { updateLogsConfig } = useActions(logsConfigLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const [value, setValue] = useState<string>('')

    useEffect(() => {
        if (logsConfig) {
            setValue(logsConfig.logs_distinct_id_attribute_key)
        }
    }, [logsConfig])

    if (!logsConfig && logsConfigLoading) {
        return <LemonSkeleton className="w-1/2 h-4" />
    }

    const trimmed = value.trim()
    const isDirty = trimmed !== (logsConfig?.logs_distinct_id_attribute_key ?? '')
    const isEmpty = trimmed.length === 0

    return (
        <div className="deprecated-space-y-4">
            <LemonInput
                value={value}
                onChange={setValue}
                placeholder={DEFAULT_LOGS_DISTINCT_ID_ATTRIBUTE_KEY}
                maxLength={200}
                disabledReason={restrictedReason}
                className="max-w-md"
            />
            <LemonButton
                type="primary"
                onClick={() => updateLogsConfig({ logs_distinct_id_attribute_key: trimmed })}
                disabledReason={
                    restrictedReason ||
                    (isEmpty ? 'Attribute key is required' : !isDirty ? 'No changes to save' : undefined)
                }
                loading={logsConfigLoading}
            >
                Save
            </LemonButton>
        </div>
    )
}
