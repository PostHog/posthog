import equal from 'fast-deep-equal'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { DEFAULT_LOGS_DISTINCT_ID_ATTRIBUTE_KEYS, logsConfigLogic } from 'products/logs/frontend/logsConfigLogic'

const MAX_KEY_LENGTH = 200

function cleanKeys(input: string[]): string[] {
    // Trim each entry, drop empties, dedupe while preserving order.
    const seen = new Set<string>()
    const cleaned: string[] = []
    for (const raw of input) {
        const trimmed = raw.trim()
        if (!trimmed || seen.has(trimmed)) {
            continue
        }
        seen.add(trimmed)
        cleaned.push(trimmed)
    }
    return cleaned
}

export function LogsDistinctIdAttributeKey(): JSX.Element {
    const { logsConfig, logsConfigLoading } = useValues(logsConfigLogic)
    const { updateLogsConfig } = useActions(logsConfigLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const [value, setValue] = useState<string[]>([])

    useEffect(() => {
        if (logsConfig) {
            setValue(logsConfig.logs_distinct_id_attribute_keys)
        }
    }, [logsConfig])

    if (!logsConfig && logsConfigLoading) {
        return <LemonSkeleton className="w-1/2 h-4" />
    }

    const cleaned = cleanKeys(value)
    const existing = logsConfig?.logs_distinct_id_attribute_keys ?? []
    const isDirty = !equal(cleaned, existing)
    const isEmpty = cleaned.length === 0
    const hasOverlongKey = cleaned.some((k) => k.length > MAX_KEY_LENGTH)

    return (
        <div className="deprecated-space-y-4 max-w-md">
            <LemonInputSelect
                mode="multiple"
                allowCustomValues
                sortable
                value={value}
                onChange={setValue}
                placeholder={DEFAULT_LOGS_DISTINCT_ID_ATTRIBUTE_KEYS[0]}
                options={[]}
                disabled={!!restrictedReason}
            />
            <p className="text-muted text-xs mt-1">
                {restrictedReason ?? (
                    <>
                        Order is priority — for each log, the first configured key found on that row is used as the
                        person identifier (priority-ordered fallback via SQL <code>coalesce</code>). Drag to reorder,
                        press Enter or paste a comma-separated list to add multiple at once.
                    </>
                )}
            </p>
            <LemonButton
                type="primary"
                onClick={() => updateLogsConfig({ logs_distinct_id_attribute_keys: cleaned })}
                disabledReason={
                    restrictedReason ||
                    (isEmpty
                        ? 'At least one attribute key is required'
                        : hasOverlongKey
                          ? `Each key must be no longer than ${MAX_KEY_LENGTH} characters`
                          : !isDirty
                            ? 'No changes to save'
                            : undefined)
                }
                loading={logsConfigLoading}
            >
                Save
            </LemonButton>
        </div>
    )
}
