import { LemonSwitch, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

export type SurveySettingsProps = {
    inModal?: boolean
}

export function SurveySettings({ inModal = false }: SurveySettingsProps): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <div className="space-y-4">
            <div className="space-y-2">
                <LemonSwitch
                    data-attr="opt-in-surveys-switch"
                    onChange={(checked) => {
                        updateCurrentTeam({
                            surveys_opt_in: checked,
                        })
                    }}
                    label="Enable surveys popup"
                    bordered={!inModal}
                    fullWidth={inModal}
                    labelClassName={inModal ? 'text-base font-semibold' : ''}
                    checked={!!currentTeam?.surveys_opt_in}
                />

                <p>
                    Please note your website needs to have the{' '}
                    <Link to={urls.settings('project', 'snippet')}>PostHog snippet</Link> or at least version 1.81.1 of{' '}
                    <Link
                        to="https://posthog.com/docs/libraries/js?utm_campaign=surveys&utm_medium=in-product"
                        target="_blank"
                    >
                        posthog-js
                    </Link>{' '}
                    directly installed. For more details, check out our{' '}
                    <Link
                        to="https://posthog.com/docs/surveys/installation?utm_campaign=surveys&utm_medium=in-product"
                        target="_blank"
                    >
                        docs
                    </Link>
                    .
                </p>
            </div>
        </div>
    )
}

export function openSurveysSettingsDialog(): void {
    LemonDialog.open({
        title: 'Surveys settings',
        content: <SurveySettings inModal />,
        width: 600,
        primaryButton: {
            children: 'Done',
        },
    })
}
