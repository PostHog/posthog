import { LemonSwitch, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

export function SettingPersonsOnEvents(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            <p>
                We have updated our data model to also store person properties directly on events, making queries
                significantly faster. This means that person properties will no longer be "timeless", but rather
                point-in-time i.e. on filters we'll consider a person's properties at the time of the event, rather than
                at present time. This may cause data to change on some of your insights, but will be the default way we
                handle person properties going forward. For now, you can control whether you want this on or not, and
                should feel free to let us know of any concerns you might have. If you do enable this, you should see
                speed improvements of around 3-5x on average on most of your insights.
                <Link to="https://github.com/PostHog/posthog/blob/75a2111f2c4f9183dd45f85c7b103c7b0524eabf/plugin-server/src/worker/ingestion/PoE.md">
                    More info.
                </Link>
            </p>

            <LemonSwitch
                data-attr={`poe-setting`}
                onChange={(checked) => {
                    updateCurrentTeam({
                        extra_settings: { ...currentTeam?.extra_settings, ['poe_v2_enabled']: checked },
                    })
                }}
                label={`Enable Person on Events (Beta)`}
                checked={!!currentTeam?.extra_settings?.['poe_v2_enabled']}
                bordered
            />
        </>
    )
}
