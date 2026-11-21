import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonInput, LemonSkeleton } from '@posthog/lemon-ui'
import { Button, Input, Skeleton, Text } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { teamLogic } from 'scenes/teamLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

export function LogsJsonParseAttributeSettings(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const savedKey = currentTeam?.logs_settings?.json_parse_logs_attribute_key ?? ''
    const [value, setValue] = useState(savedKey)

    useEffect(() => {
        setValue(savedKey)
    }, [savedKey])

    if (!currentTeam) {
        return todayRailNav ? <Skeleton className="h-8 max-w-md" /> : <LemonSkeleton className="w-1/2 h-4" />
    }

    const trimmed = value.trim()
    const saveDisabledReason = restrictedReason || (trimmed === savedKey ? 'No changes to save' : undefined)

    const handleSave = (): void =>
        updateCurrentTeam({
            logs_settings: { ...currentTeam.logs_settings, json_parse_logs_attribute_key: trimmed },
        })

    if (todayRailNav) {
        const accessControlDisabledReason = getAccessControlDisabledReason(
            AccessControlResourceType.Logs,
            AccessControlLevel.Editor
        )

        return (
            <div className="flex flex-col items-start gap-2">
                <Input
                    value={value}
                    onChange={(event) => setValue(event.target.value)}
                    maxLength={200}
                    placeholder="e.g. attributes"
                    aria-label="JSON log attribute key"
                    disabled={currentTeamLoading}
                    disabledReason={restrictedReason ?? accessControlDisabledReason}
                    data-attr="logs-json-parse-attribute-key"
                    className="max-w-md"
                />
                <Text size="xs" variant="muted" render={<p className="m-0 max-w-200" />}>
                    Parse JSON in this log attribute on new logs. Nested fields become dotted attributes, such as{' '}
                    <code>attributes.sessionId</code>. PostHog adds up to 50 fields per log. Use those keys in Link to
                    person or Link to session. The original attribute and existing values are kept. Invalid JSON is left
                    unchanged. Clear the key and save to disable.
                </Text>
                <AccessControlAction
                    resourceType={AccessControlResourceType.Logs}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <Button
                        variant="primary"
                        onClick={handleSave}
                        disabledReason={saveDisabledReason}
                        loading={currentTeamLoading}
                    >
                        Save
                    </Button>
                </AccessControlAction>
            </div>
        )
    }

    return (
        <div className="deprecated-space-y-4">
            <AccessControlAction
                resourceType={AccessControlResourceType.Logs}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <LemonInput
                    value={value}
                    onChange={setValue}
                    maxLength={200}
                    placeholder="e.g. attributes"
                    aria-label="JSON log attribute key"
                    disabled={currentTeamLoading || !!restrictedReason}
                    data-attr="logs-json-parse-attribute-key"
                    className="max-w-md"
                />
            </AccessControlAction>
            <p className="text-secondary text-sm max-w-200">
                Parse JSON in this log attribute on new logs. Nested fields become dotted attributes, such as{' '}
                <code>attributes.sessionId</code>. PostHog adds up to 50 fields per log. Use those keys in Link to
                person or Link to session. The original attribute and existing values are kept. Invalid JSON is left
                unchanged. Clear the key and save to disable.
            </p>
            <AccessControlAction
                resourceType={AccessControlResourceType.Logs}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <LemonButton
                    type="primary"
                    onClick={handleSave}
                    disabledReason={saveDisabledReason}
                    loading={currentTeamLoading}
                >
                    Save
                </LemonButton>
            </AccessControlAction>
        </div>
    )
}
