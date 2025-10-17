import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonSwitch, LemonTag } from '@posthog/lemon-ui'

import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { NotificationSettings } from '~/types'

type BooleanNotificationSettings = Omit<NotificationSettings, 'project_weekly_digest_disabled'>

const NOTIFICATION_DEFAULTS: BooleanNotificationSettings = {
    plugin_disabled: true,
    error_tracking_issue_assigned: true,
    discussions_mentioned: true,
    all_weekly_digest_disabled: false,
}

export function UpdateEmailPreferences(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const { updateWeeklyDigestForTeam, updateWeeklyDigestForAllTeams } = useActions(userLogic)
    const { currentOrganization } = useValues(organizationLogic)

    const weeklyDigestEnabled = !user?.notification_settings?.all_weekly_digest_disabled
    const [weeklyDigestProjectsExpanded, setWeeklyDigestProjectsExpanded] = useState(weeklyDigestEnabled)

    return (
        <div className="deprecated-space-y-4">
            <h3>Email notifications</h3>
            <p>Configure which email notifications you want to receive.</p>

            <div className="deprecated-space-y-4">
                <div className="deprecated-space-y-4">
                    <h4>Notification types</h4>

                    {/* Weekly Digest Section */}
                    <div className="border rounded p-4 deprecated-space-y-3">
                        <SimpleSwitch
                            setting="all_weekly_digest_disabled"
                            label="Weekly digest"
                            description="The weekly digest keeps you up to date with everything that's happening in your PostHog organizations"
                            dataAttr="weekly_digest_enabled"
                            // because the setting is disabled, but the control is expressed as enabled
                            inverse={true}
                        />

                        {weeklyDigestEnabled && (
                            <div>
                                <LemonButton
                                    icon={weeklyDigestProjectsExpanded ? <IconChevronDown /> : <IconChevronRight />}
                                    onClick={() => setWeeklyDigestProjectsExpanded(!weeklyDigestProjectsExpanded)}
                                    size="small"
                                    type="tertiary"
                                    className="p-0"
                                >
                                    Select projects ({currentOrganization?.teams?.length || 0} available)
                                </LemonButton>

                                {weeklyDigestProjectsExpanded && (
                                    <div className="mt-3 ml-6 deprecated-space-y-2">
                                        <div className="flex flex-col gap-2">
                                            <div className="flex flex-row items-center gap-4">
                                                <LemonButton
                                                    size="xsmall"
                                                    type="secondary"
                                                    onClick={() => {
                                                        updateWeeklyDigestForAllTeams(
                                                            (currentOrganization?.teams || []).map((t) => t.id),
                                                            true
                                                        )
                                                    }}
                                                >
                                                    Enable for all teams
                                                </LemonButton>
                                                <LemonButton
                                                    size="xsmall"
                                                    type="secondary"
                                                    onClick={() => {
                                                        updateWeeklyDigestForAllTeams(
                                                            (currentOrganization?.teams || []).map((t) => t.id),
                                                            false
                                                        )
                                                    }}
                                                >
                                                    Disable for all teams
                                                </LemonButton>
                                            </div>

                                            {currentOrganization?.teams?.map((team) => (
                                                <LemonCheckbox
                                                    key={`weekly-digest-${team.id}`}
                                                    id={`weekly-digest-${team.id}`}
                                                    data-attr={`weekly_digest_${team.id}`}
                                                    onChange={(checked) => updateWeeklyDigestForTeam(team.id, checked)}
                                                    checked={
                                                        !user?.notification_settings.project_weekly_digest_disabled?.[
                                                            team.id
                                                        ]
                                                    }
                                                    disabled={userLoading}
                                                    label={
                                                        <div className="flex items-center gap-2">
                                                            <span>{team.name}</span>
                                                            <LemonTag type="muted">id: {team.id.toString()}</LemonTag>
                                                        </div>
                                                    }
                                                />
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </div>
                        )}
                    </div>

                    <div className="border rounded p-4">
                        <SimpleSwitch
                            setting="plugin_disabled"
                            label="Data pipeline errors"
                            description="Get notified when data pipeline components (destinations, batch exports) encounter errors for all projects"
                            dataAttr="pipeline_errors_enabled"
                        />
                    </div>

                    <div className="border rounded p-4">
                        <SimpleSwitch
                            setting="error_tracking_issue_assigned"
                            label="Issue assigned"
                            description="Stay on top of your bugs with a notification every time an issue is assigned to you or your role"
                            dataAttr="error_tracking_issue_assigned_enabled"
                        />
                    </div>

                    <div className="border rounded p-4">
                        <SimpleSwitch
                            setting="discussions_mentioned"
                            label="Comment mentions"
                            description="Get notified when someone mentions you in a discussion on any project"
                            dataAttr="discussions_mentioned_enabled"
                        />
                    </div>
                </div>
            </div>
        </div>
    )
}

const SimpleSwitch = ({
    dataAttr,
    label,
    description,
    setting,
    inverse = false,
}: {
    dataAttr: string
    label: string
    description: string
    setting: keyof BooleanNotificationSettings
    /**
     * Some settings are expressed as "disabled" but the control is expressed as "enabled" (e.g. "All weekly digests" setting). 🫠
     */
    inverse?: boolean
}): JSX.Element => {
    const { user, userLoading } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)

    const value = user?.notification_settings?.[setting]
    let checked = value ?? NOTIFICATION_DEFAULTS[setting]
    if (inverse) {
        checked = !checked
    }

    return (
        <div className="space-y-2">
            <LemonSwitch
                data-attr={dataAttr}
                onChange={(newChecked) => {
                    user?.notification_settings &&
                        updateUser({
                            notification_settings: {
                                ...user?.notification_settings,
                                [setting]: inverse ? !newChecked : newChecked,
                            },
                        })
                }}
                checked={checked}
                disabled={userLoading}
                label={label}
            />
            <span className="text-muted">{description}</span>
        </div>
    )
}
