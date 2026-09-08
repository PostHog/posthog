import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { objectsEqual } from 'lib/utils/objects'

import {
    DEFAULT_TRACING_DISTINCT_ID_ATTRIBUTE_KEYS,
    tracingCorrelationConfigLogic,
} from 'products/tracing/frontend/tracingCorrelationConfigLogic'

export function TracingDistinctIdAttributeKeys(): JSX.Element {
    const { tracingConfig, tracingConfigLoading } = useValues(tracingCorrelationConfigLogic)
    const { updateTracingConfig } = useActions(tracingCorrelationConfigLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const [value, setValue] = useState<string[]>([])

    useEffect(() => {
        if (tracingConfig) {
            setValue(tracingConfig.tracing_distinct_id_attribute_keys ?? DEFAULT_TRACING_DISTINCT_ID_ATTRIBUTE_KEYS)
        }
    }, [tracingConfig])

    if (!tracingConfig && tracingConfigLoading) {
        return <LemonSkeleton className="w-1/2 h-4" />
    }

    const cleaned = value.map((key) => key.trim()).filter(Boolean)
    const isDirty = !objectsEqual(cleaned, tracingConfig?.tracing_distinct_id_attribute_keys ?? [])
    const isEmpty = cleaned.length === 0

    return (
        <div className="deprecated-space-y-4">
            <LemonInputSelect
                mode="multiple"
                allowCustomValues
                value={value}
                onChange={setValue}
                placeholder={DEFAULT_TRACING_DISTINCT_ID_ATTRIBUTE_KEYS.join(', ')}
                loading={tracingConfigLoading}
                disabled={tracingConfigLoading || !!restrictedReason}
                data-attr="tracing-distinct-id-attribute-keys-select"
                className="max-w-md"
            />
            <LemonButton
                type="primary"
                onClick={() => updateTracingConfig({ tracing_distinct_id_attribute_keys: cleaned })}
                disabledReason={
                    restrictedReason ||
                    (isEmpty ? 'At least one attribute key is required' : !isDirty ? 'No changes to save' : undefined)
                }
                loading={tracingConfigLoading}
            >
                Save
            </LemonButton>
        </div>
    )
}
