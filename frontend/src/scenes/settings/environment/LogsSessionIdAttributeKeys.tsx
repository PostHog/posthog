import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'
import { Button, Skeleton } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const [value, setValue] = useState<string[]>([])

    useEffect(() => {
        if (logsConfig) {
            setValue(logsConfig.logs_session_id_attribute_keys ?? DEFAULT_LOGS_SESSION_ID_ATTRIBUTE_KEYS)
        }
    }, [logsConfig])

    if (!logsConfig && logsConfigLoading) {
        return todayRailNav ? <Skeleton className="h-8 max-w-md" /> : <LemonSkeleton className="w-1/2 h-4" />
    }

    const cleaned = value.map((key) => key.trim()).filter(Boolean)
    const isDirty = !objectsEqual(cleaned, logsConfig?.logs_session_id_attribute_keys ?? [])
    const isEmpty = cleaned.length === 0
    const saveDisabledReason =
        restrictedReason ||
        (isEmpty ? 'At least one attribute key is required' : !isDirty ? 'No changes to save' : undefined)

    const handleSave = (): void => updateLogsConfig({ logs_session_id_attribute_keys: cleaned })

    if (todayRailNav) {
        return (
            <div className="flex flex-col items-start gap-2 max-w-md">
                <TagsCombobox
                    value={value}
                    onChange={setValue}
                    customValueNoun="attribute key"
                    dataAttr="logs-session-id-attribute-keys-select"
                    placeholder={DEFAULT_LOGS_SESSION_ID_ATTRIBUTE_KEYS.join(', ')}
                    disabled={logsConfigLoading}
                    disabledReason={restrictedReason}
                    className="w-full"
                />
                <Button
                    variant="primary"
                    onClick={handleSave}
                    disabledReason={saveDisabledReason}
                    loading={logsConfigLoading}
                >
                    Save
                </Button>
            </div>
        )
    }

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
                onClick={handleSave}
                disabledReason={saveDisabledReason}
                loading={logsConfigLoading}
            >
                Save
            </LemonButton>
        </div>
    )
}
