import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonSwitch, LemonTag } from '@posthog/lemon-ui'

import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

export function UpdateEmailPreferences(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)
    const { currentOrganization } = useValues(organizationLogic)

    const weeklyDigestEnabled = !user?.notification_settings?.all_weekly_digest_disabled
    const [weeklyDigestProjectsExpanded, setWeeklyDigestProjectsExpanded] = useState(weeklyDigestEnabled)
    const pipelineErrorsEnabled = user?.notification_settings?.plugin_disabled ?? true

    const updateWeeklyDigestForProject = (teamId: number, enabled: boolean): void => {
        if (!user?.notification_settings) {
            return
        }

        updateUser({
            notification_settings: {
                ...user.notification_settings,
                project_weekly_digest_disabled: {
                    ...user.notification_settings.project_weekly_digest_disabled,
                    [teamId]: !enabled,
                },
            },
        })
    }

    return (
        <div className="deprecated-space-y-4">
            <h3>Email notifications</h3>
            <p>Configure which email notifications you want to receive.</p>

            <div className="deprecated-space-y-4">
                <div className="deprecated-space-y-4">
                    <h4>Notification types</h4>

                    {/* Weekly Digest Section */}
                    <div className="border rounded p-4 deprecated-space-y-3">
                        <LemonSwitch
                            id="weekly-digest-enabled"
                            data-attr="weekly_digest_enabled"
                            onChange={() => {
                                user?.notification_settings &&
                                    updateUser({
                                        notification_settings: {
                                            ...user?.notification_settings,
                                            all_weekly_digest_disabled:
                                                !user?.notification_settings.all_weekly_digest_disabled,
                                        },
                                    })
                            }}
                            checked={weeklyDigestEnabled}
                            disabled={userLoading}
                            label="Weekly digest"
                        />
                        <p className="text-muted mt-2">
                            The weekly digest keeps you up to date with everything that's happening in your PostHog
                            organizations.
                        </p>

                        {weeklyDigestEnabled && (
                            <div className="ml-6">
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
                                            {currentOrganization?.teams?.map((team) => (
                                                <LemonCheckbox
                                                    key={`weekly-digest-${team.id}`}
                                                    id={`weekly-digest-${team.id}`}
                                                    data-attr={`weekly_digest_${team.id}`}
                                                    onChange={(checked) =>
                                                        updateWeeklyDigestForProject(team.id, checked)
                                                    }
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

                    {/* Data Pipeline Errors Section */}
                    <div className="border rounded p-4 deprecated-space-y-3">
                        <LemonSwitch
                            id="pipeline-errors-enabled"
                            data-attr="pipeline_errors_enabled"
                            onChange={() => {
                                user?.notification_settings &&
                                    updateUser({
                                        notification_settings: {
                                            ...user?.notification_settings,
                                            plugin_disabled: !user?.notification_settings.plugin_disabled,
                                        },
                                    })
                            }}
                            checked={pipelineErrorsEnabled}
                            disabled={userLoading}
                            label="Data pipeline errors"
                            tooltip="Get notified when data pipeline components (destinations, batch exports) encounter errors for all projects"
                        />
                    </div>
                </div>
            </div>
        </div>
    )
}
