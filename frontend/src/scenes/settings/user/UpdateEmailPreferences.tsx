import { LemonSwitch, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

export function UpdateEmailPreferences(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)
    const { currentOrganization } = useValues(organizationLogic)

    return (
        <div className="deprecated-space-y-4">
            <LemonSwitch
                id="plugin-disabled"
                data-attr="plugin_disabled"
                onChange={() => {
                    user?.notification_settings &&
                        updateUser({
                            notification_settings: {
                                ...user?.notification_settings,
                                plugin_disabled: !user?.notification_settings.plugin_disabled,
                            },
                        })
                }}
                checked={user?.notification_settings.plugin_disabled || false}
                disabled={userLoading}
                bordered
                label="Get notified of data pipeline errors."
            />

            <h3>Weekly digest</h3>
            <p>
                The weekly digest keeps you up to date with everything that's happening in your PostHog organizations.
            </p>
            <div className="deprecated-space-y-2">
                <LemonSwitch
                    id="all-digests-disabled"
                    data-attr="all_digests_disabled"
                    onChange={() => {
                        user?.notification_settings &&
                            updateUser({
                                notification_settings: {
                                    ...user?.notification_settings,
                                    all_weekly_digest_disabled: !user?.notification_settings.all_weekly_digest_disabled,
                                },
                            })
                    }}
                    checked={!user?.notification_settings.all_weekly_digest_disabled}
                    disabled={userLoading}
                    bordered
                    label="Receive the weekly digests"
                    tooltip="This option applies to all organizations you belong to. If you want to opt out of digests for a specific organization, disable all the individual project settings below."
                />
                {!user?.notification_settings.all_weekly_digest_disabled ? (
                    <>
                        <h4 className="ml-12">Individual project settings:</h4>
                        <ul className="flex flex-col gap-2 w-fit">
                            {currentOrganization?.teams?.map((team) => (
                                <li key={team.id} className="ml-16 grow list-disc">
                                    <div className="flex items-center grow">
                                        <LemonSwitch
                                            id={`project-digest-${team.id}`}
                                            data-attr={`project_digest_${team.id}`}
                                            onChange={() => {
                                                user?.notification_settings &&
                                                    updateUser({
                                                        notification_settings: {
                                                            ...user?.notification_settings,
                                                            project_weekly_digest_disabled: {
                                                                ...user.notification_settings
                                                                    .project_weekly_digest_disabled,
                                                                [team.id]:
                                                                    !user.notification_settings
                                                                        .project_weekly_digest_disabled?.[team.id],
                                                            },
                                                        },
                                                    })
                                            }}
                                            checked={
                                                !user?.notification_settings.project_weekly_digest_disabled?.[team.id]
                                            }
                                            disabled={
                                                userLoading || user?.notification_settings.all_weekly_digest_disabled
                                            }
                                            bordered
                                            label={
                                                <>
                                                    {team.name}
                                                    <LemonTag type="muted" className="ml-2">
                                                        id: {team.id.toString()}
                                                    </LemonTag>
                                                </>
                                            }
                                            fullWidth
                                        />
                                    </div>
                                </li>
                            ))}
                        </ul>
                    </>
                ) : null}
            </div>
        </div>
    )
}
