import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import {
    DEFAULT_TRACING_DISTINCT_ID_ATTRIBUTE_KEY,
    tracingConfigLogic,
} from 'products/tracing/frontend/tracingConfigLogic'

export function TracingDistinctIdAttributeKey(): JSX.Element {
    const { tracingConfig, tracingConfigLoading } = useValues(tracingConfigLogic)
    const { updateTracingConfig } = useActions(tracingConfigLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const [value, setValue] = useState<string>('')

    useEffect(() => {
        if (tracingConfig) {
            setValue(tracingConfig.tracing_distinct_id_attribute_key)
        }
    }, [tracingConfig])

    if (!tracingConfig && tracingConfigLoading) {
        return <LemonSkeleton className="w-1/2 h-4" />
    }

    const trimmed = value.trim()
    const isDirty = trimmed !== (tracingConfig?.tracing_distinct_id_attribute_key ?? '')
    const isEmpty = trimmed.length === 0

    return (
        <div className="deprecated-space-y-4">
            <LemonInput
                value={value}
                onChange={setValue}
                placeholder={DEFAULT_TRACING_DISTINCT_ID_ATTRIBUTE_KEY}
                maxLength={200}
                disabledReason={restrictedReason}
                className="max-w-md"
            />
            <LemonButton
                type="primary"
                onClick={() => updateTracingConfig({ tracing_distinct_id_attribute_key: trimmed })}
                disabledReason={
                    restrictedReason ||
                    (isEmpty ? 'Attribute key is required' : !isDirty ? 'No changes to save' : undefined)
                }
                loading={tracingConfigLoading}
            >
                Save
            </LemonButton>
        </div>
    )
}
