import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonInput, LemonSkeleton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

export function LogsJsonParseAttributeSettings(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const savedKey = currentTeam?.logs_settings?.json_parse_logs_attribute_key ?? ''
    const [value, setValue] = useState(savedKey)

    useEffect(() => {
        setValue(savedKey)
    }, [savedKey])

    if (!currentTeam) {
        return <LemonSkeleton className="w-1/2 h-4" />
    }

    const trimmed = value.trim()

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
                    onClick={() =>
                        updateCurrentTeam({
                            logs_settings: { ...currentTeam.logs_settings, json_parse_logs_attribute_key: trimmed },
                        })
                    }
                    disabledReason={restrictedReason || (trimmed === savedKey ? 'No changes to save' : undefined)}
                    loading={currentTeamLoading}
                >
                    Save
                </LemonButton>
            </AccessControlAction>
        </div>
    )
}
