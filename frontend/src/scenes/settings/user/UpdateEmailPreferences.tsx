import { LemonCheckbox, LemonSwitch, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

export function UpdateEmailPreferences(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)
    const { currentOrganization } = useValues(organizationLogic)

    const weeklyDigestEnabled = !user?.notification_settings?.all_weekly_digest_disabled
    const pipelineErrorsEnabled = !user?.notification_settings?.plugin_disabled

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
            <p>Configure which email notifications you want to receive and for which projects.</p>

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
                            tooltip="Receive weekly summaries of activity in your projects"
                        />

                        {weeklyDigestEnabled && (
                            <div className="ml-8 deprecated-space-y-2">
                                <p className="text-muted text-sm">
                                    Select which projects to receive weekly digests for:
                                </p>
                                <div className="flex flex-col gap-2">
                                    {currentOrganization?.teams?.map((team) => (
                                        <LemonCheckbox
                                            key={`weekly-digest-${team.id}`}
                                            id={`weekly-digest-${team.id}`}
                                            data-attr={`weekly_digest_${team.id}`}
                                            onChange={(checked) => updateWeeklyDigestForProject(team.id, checked)}
                                            checked={
                                                !user?.notification_settings.project_weekly_digest_disabled?.[team.id]
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
                            tooltip="Get notified when data pipeline components (destinations, batch exports) encounter errors"
                        />

                        {pipelineErrorsEnabled && (
                            <div className="ml-8 deprecated-space-y-2">
                                <p className="text-muted text-sm">
                                    Pipeline error notifications will be sent for all projects. Project-specific
                                    settings will be available in a future update.
                                </p>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    )
}
