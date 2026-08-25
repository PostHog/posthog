import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { objectsEqual } from 'lib/utils/objects'

import { DEFAULT_LOGS_SESSION_ID_ATTRIBUTE_KEYS, logsConfigLogic } from 'products/logs/frontend/logsConfigLogic'

export function LogsSessionIdAttributeKeys(): JSX.Element {
    const { logsConfig, logsConfigLoading } = useValues(logsConfigLogic)
    const { updateLogsConfig } = useActions(logsConfigLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const [value, setValue] = useState<string[]>([])

    useEffect(() => {
        if (logsConfig) {
            setValue(logsConfig.logs_session_id_attribute_keys ?? DEFAULT_LOGS_SESSION_ID_ATTRIBUTE_KEYS)
        }
    }, [logsConfig])

    if (!logsConfig && logsConfigLoading) {
        return <LemonSkeleton className="w-1/2 h-4" />
    }

    const cleaned = value.map((key) => key.trim()).filter(Boolean)
    const isDirty = !objectsEqual(cleaned, logsConfig?.logs_session_id_attribute_keys ?? [])
    const isEmpty = cleaned.length === 0

    return (
        <div className="deprecated-space-y-4">
            <LemonInputSelect
                mode="multiple"
                allowCustomValues
                value={value}
                onChange={setValue}
                placeholder={DEFAULT_LOGS_SESSION_ID_ATTRIBUTE_KEYS.join(', ')}
                loading={logsConfigLoading}
                disabled={logsConfigLoading || !!restrictedReason}
                data-attr="logs-session-id-attribute-keys-select"
                className="max-w-md"
            />
            <LemonButton
                type="primary"
                onClick={() => updateLogsConfig({ logs_session_id_attribute_keys: cleaned })}
                disabledReason={
                    restrictedReason ||
                    (isEmpty ? 'At least one attribute key is required' : !isDirty ? 'No changes to save' : undefined)
                }
                loading={logsConfigLoading}
            >
                Save
            </LemonButton>
        </div>
    )
}
