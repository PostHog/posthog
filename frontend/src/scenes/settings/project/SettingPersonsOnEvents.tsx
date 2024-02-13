import { LemonSwitch, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

export function SettingPersonsOnEvents(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            <p>
                We have updated our data model to store person properties directly on events, making queries
                significantly faster. This means that person properties will no longer be "timeless", but rather
                point-in-time i.e. on filters we'll consider a person's properties at the time of the event, rather than
                at present time. This may cause data to change on some of your insights, but will be the default way we
                handle person properties going forward. For now, you can control whether you want this on or not, and
                should feel free to let us know of any concerns you might have. If you do enable this, you should see
                speed improvements of around 3-5x on average on most of your insights.
            </p>
            <p>
                Please note, <strong>you might need to change the way you send us events</strong> after enabling this
                feature. <Link to="https://github.com/PostHog/meta/issues/173">Read more here.</Link>
            </p>

            <LemonSwitch
                data-attr="poe-setting"
                onChange={(checked) => {
                    updateCurrentTeam({
                        extra_settings: { ...currentTeam?.extra_settings, ['poe_v2_enabled']: checked },
                    })
                }}
                label="Enable Person on Events (Beta)"
                checked={!!currentTeam?.extra_settings?.['poe_v2_enabled']}
                bordered
            />
        </>
    )
}
